import sys
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import serial
import time
import os
import queue
from datetime import datetime
import threading
import csv 

GPIO_OK = True

try:

    from gpiozero import Device, Button

    # Prefer LGPIO on Bookworm; fallback to RPi.GPIO if LGPIO missing

    try:
        from gpiozero.pins.lgpio import LGPIOFactory
        Device.pin_factory = LGPIOFactory()
        print("GPIOZero: using LGPIOFactory")

    except Exception as e:
        print("LGPIOFactory not available:", e)
        from gpiozero.pins.rpigpio import RPiGPIOFactory

        Device.pin_factory = RPiGPIOFactory()
        print("GPIOZero: using RPiGPIOFactory")

except Exception as e:
    print("gpiozero not available:", e)
    GPIO_OK = False
    Button = None

SW_PIN = 17
DEBOUNCE = 0.02  # 20 ms

# =============================================================

app = Flask(__name__)

def save_iterations_to_csv():
    """
    Save all iterations_data to a timestamped CSV file is the GAME RESULTS folder.
    """
    results_folder = "GAME RESULTS"
    if not os.path.exists(results_folder):
        os.makedirs(results_folder)
        print(f"Created folder: {results_folder}")

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(results_folder, f"results_{ts}.csv")
    fieldnames = [
        "iteration",
        "plan",
        "actual",
        "defects",
        "in_progress",
        "effective_in_progress",  # *** NEW ***
        "delta_in_process",       # *** NEW ***
        "total",
        "delta",
        "ipoints",                # *** NEW ***
        "lmax_points",            # *** NEW ***
        "timestamp",
        "team_players",  
    ]

    with open(filename, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in state["iterations_data"]:
            writer.writerow(row)

    print(f"Results saved to {filename}")
    return filename

# Simplified state for Agile Game
state = {
    "current_iteration": 1,
    "plan_number": 0,
    "ball_count": 0,
    "is_counting": False,
    "iterations_data": [],
    "number_of_players": 0
}

state_lock = threading.Lock()
# Queue used to push live counts to SSE clients
updates_q = queue.Queue()

# No-op to keep earlier call

def reset_arduino():
    pass
# Will be set in __main__
button = None


@app.route('/')
def dashboard():
    return render_template('dashboard.html', 
                         current_iteration=state["current_iteration"],
                         plan_number=state["plan_number"],
                         iterations_data=state["iterations_data"],
                         number_of_players=state["number_of_players"])

@app.route('/set_players', methods=['POST'])
def set_players():
    """Set the number of players for the game"""
    players = request.json.get('players', 0)
    state["number_of_players"] = players
    return jsonify({"success": True, "players": players})

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
      
    # clear stale updates, then push initial 
    while not updates_q.empty():
        try: 
            updates_q.get_nowait()
        except queue.Empty: 
            break
    updates_q.put(0)

    

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
    in_progress = request.json.get('in_progress', 0)  
    actual = state["ball_count"]
    plan = state["plan_number"]

    # Calculate results
    total = actual - defects
    delta = total - plan 

    # Calculate results
    total = actual - defects
    delta = total - plan 
    
    # Calculate scoring with capped and weighted in-progress 
    effective_in_progress = min(in_progress, 20)      # Cap at 20 balls
    delta_in_process = effective_in_progress * 0.25   # Multiply by 0.25
    
    ipoints = round(delta + delta_in_process)         # Round to whole number 
    lmax_points = delta + 5                           # Iteration max points (already whole)

    # Store iteration data
    iteration_data = {
        "iteration": state["current_iteration"],
        "plan": plan,
        "actual": actual,
        "defects": defects,
        "in_progress": in_progress,
        "effective_in_progress": effective_in_progress,     
        "delta_in_process": round(delta_in_process, 2),     # Keep 2 decimals for data
        "total": total,
        "delta": delta,
        "ipoints": ipoints,                                 # rounded above
        "lmax_points": lmax_points,                         
        "timestamp": datetime.now().isoformat(),
        "team_players": state["number_of_players"],

    }

    with state_lock:
        state["iterations_data"].append(iteration_data)
        game_complete = len(state["iterations_data"]) == 5

        if state["current_iteration"] < 5:
            state["current_iteration"] += 1

    if game_complete:
        save_iterations_to_csv()
    return jsonify({
        "success": True,
        "iteration_data": iteration_data,
        "current_iteration": state["current_iteration"]
    })

@app.route('/get_current_count')
def get_current_count():
    """Get current ball count"""
    return jsonify({"count": state["ball_count"]})

@app.route('/get_final_results')
def get_final_results():
    """Get final results for all iterations"""
    return jsonify({
        "success": True,
        "iterations_data": state["iterations_data"],
        "total_iterations": len(state["iterations_data"]),
        "game_complete": len(state["iterations_data"]) == 5,
        "number_of_players": state["number_of_players"]
    })

@app.route('/live_counter')
def live_counter():
    """SSE stream that emits the latest count whenever it changes."""

    @stream_with_context
    def stream():
        yield "event: hello\ndata: connected\n\n"
        while True:
            # if not counting, send idle pings so the connection stays up
            with state_lock:
                counting = state["is_counting"]

            if not counting:
                time.sleep(1.0)
                yield "event: status\ndata: idle\n\n"
                continue

            try:
                cnt = updates_q.get(timeout=15.0)
                yield f"data: {cnt}\n\n"

            except queue.Empty:
                yield "event: ping\ndata: keep-alive\n\n"
    return Response(stream(), mimetype="text/event-stream")

@app.route('/reset_system', methods=['POST'])

def reset_system():
    """Reset entire system"""
    state["current_iteration"] = 1
    state["plan_number"] = 0
    state["ball_count"] = 0
    state["is_counting"] = False
    state["iterations_data"] = []
    state["number_of_players"] = 0 
    return jsonify({"success": True})

# ========= Initialization called once ==========================
def init_gpio_once():
    """Create Button and attach the same on_press pattern as your test script."""
    global button

    if not GPIO_OK:
        print("GPIO not available; running web app without hardware.")
        return

    def on_press():
        with state_lock:
            if not state["is_counting"]:
                return

            state["ball_count"] += 1
            new_cnt = state["ball_count"]
        updates_q.put(new_cnt)  # push to SSE listeners

        print(f"Count: {new_cnt}")

    button = Button(SW_PIN, pull_up=True, bounce_time=DEBOUNCE)
    button.when_pressed = on_press
    print("GPIO17 initialized with pull_up=True, debounce=20ms")

#====================================================

if __name__ == '__main__':
    try:
        init_gpio_once()

    except Exception as e:
        print("Failed to init GPIO17:", e)
    print("Starting Agile Game Server...")
    print("Access the game at: http://localhost:5000")

    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)