import sys
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import serial
import time
import os
from datetime import datetime
import threading
import random

app = Flask(__name__)

# Simplified state for Agile Game
state = {
    "current_iteration": 1,
    "plan_number": 0,
    "ball_count": 0,
    "is_counting": False,
    "iterations_data": []
}

def reset_arduino():
    """Reset Arduino counter to 0"""
    ############################### WITHOUT ARDUINO ########################################
    print("Arduino reset skipped - no hardware connected")
    state["ball_count"] = 0

    ############################### WITH ARDUINO ########################################
    # try:
    #     arduino = serial.Serial(port='/dev/ttyACM0', baudrate=9600, timeout=0.5)
    #     time.sleep(0.5)
    #     arduino.write(b'r')
        
    #     # Wait for confirmation
    #     deadline = time.time() + 0.5
    #     while time.time() < deadline:
    #         response = arduino.readline().decode().strip()
    #         if "Counter reset to 0" in response:
    #             break
        
    #     state["ball_count"] = 0
    #     arduino.close()
    # except serial.SerialException as e:
    #     print(f"Error: {e}")

def get_arduino_connection():
    """Get Arduino serial connection"""
    ############################### WITHOUT ARDUINO ########################################
    print("Arduino connection skipped - no hardware connected")
    return None

    ############################### WITH ARDUINO ########################################
    # try:
    #     arduino = serial.Serial(port='/dev/ttyACM0', baudrate=9600, timeout=1)
    #     time.sleep(2)
    #     return arduino
    # except Exception as e:
    #     print(f"Error connecting to Arduino: {e}")
    #     return None

@app.route('/')
def dashboard():
    """Main dashboard with table view"""
    return render_template('dashboard.html', 
                         current_iteration=state["current_iteration"],
                         plan_number=state["plan_number"],
                         iterations_data=state["iterations_data"])

@app.route('/set_plan', methods=['POST'])
def set_plan():
    """Set the plan number for all iterations"""
    plan = request.json.get('plan', 0)
    state["plan_number"] = plan
    return jsonify({"success": True, "plan": plan})

@app.route('/start_iteration', methods=['POST'])
def start_iteration():
    """Start a 2-minute counting iteration"""
    if state["is_counting"]:
        return jsonify({"error": "Already counting"}), 400
    
    # Reset Arduino counter
    reset_arduino()
    
    # Start counting
    state["is_counting"] = True
    state["ball_count"] = 0
    
    return jsonify({
        "success": True, 
        "iteration": state["current_iteration"]
    })

@app.route('/stop_iteration', methods=['POST'])
def stop_iteration():
    """Stop the current iteration"""
    state["is_counting"] = False
    
    return jsonify({
        "success": True,
        "final_count": state["ball_count"]
    })

@app.route('/submit_defects', methods=['POST'])
def submit_defects():
    """Submit defects and calculate results"""
    defects = request.json.get('defects', 0)
    actual = state["ball_count"]
    plan = state["plan_number"]
    
    # Calculate results
    total = actual - defects
    delta = total - plan
    
    # Store iteration data
    iteration_data = {
        "iteration": state["current_iteration"],
        "plan": plan,
        "actual": actual,
        "defects": defects,
        "total": total,
        "delta": delta,
        "timestamp": datetime.now().isoformat()
    }
    
    state["iterations_data"].append(iteration_data)
    
    # Move to next iteration
    if state["current_iteration"] < 5:
        state["current_iteration"] += 1
    
    return jsonify({
        "success": True,
        "iteration_data": iteration_data,
        "current_iteration": state["current_iteration"]
    })

@app.route('/get_current_count')
def get_current_count():
    """Get current ball count"""
    return jsonify({"count": state["ball_count"]})

@app.route('/live_counter')
def live_counter():
    """Server-sent events for live ball counting"""
    ############################### WITHOUT ARDUINO ########################################
    def stream():
        # Simulate ball counting without Arduino
        print("Starting live counter stream")
        count = 0
        
        while state["is_counting"]:
            time.sleep(random.uniform(1.0, 3.0))  # Random interval between balls
            
            if state["is_counting"]:  # Check if still counting
                count += random.randint(1, 2)  # Add 1-2 balls
                state["ball_count"] = count
                print(f"Simulated ball count: {count}")
                yield f"data: {count}\n\n"
        
        print("Live counter stream ended")
    
    return Response(stream_with_context(stream()), mimetype="text/event-stream")

    ############################### WITH ARDUINO ########################################
    # def stream():
    #     arduino = get_arduino_connection()
    #     if arduino:
    #         try:
    #             while state["is_counting"]:
    #                 response = arduino.readline().decode().strip()
    #                 if response.isdigit():
    #                     state["ball_count"] = int(response)
    #                     yield f"data: {response}\n\n"
    #         except Exception as e:
    #             print(f"Error in live counter: {e}")
    #         finally:
    #             arduino.close()
    
    # return Response(stream_with_context(stream()), mimetype="text/event-stream")

@app.route('/reset_system', methods=['POST'])
def reset_system():
    """Reset entire system"""
    state["current_iteration"] = 1
    state["plan_number"] = 0
    state["ball_count"] = 0
    state["is_counting"] = False
    state["iterations_data"] = []
    
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Starting Agile Game Server...")
    print("Access the game at: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)