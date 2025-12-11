import sys
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import serial
import time
import os
import queue
from datetime import datetime
import threading
import csv
import math 

GPIO_OK = True

try:
    from gpiozero import Device, Button
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

DEBOUNCE = 0.02
app = Flask(__name__)
# =============================================================
def compute_score(balls_collected: int,
                  goal_target: int,
                  in_process_balls: int) -> float:
    """
    Returns ONLY the final total score.
    All inputs are ints.
    """
    

    # Fixed parameters
    amp = 20.0
    mu_factor = 1.0
    sigma = 4.0
    baseline = 100.0
    ndigits = 3

    # ----- Goal scoring -----
    if balls_collected <= 0:
        goal_score = 0.0
    else:
        exponent = -((balls_collected - mu_factor * goal_target) ** 2) / (2 * (sigma ** 2))
        mult = amp * math.exp(exponent) + baseline
        mult = round(mult, ndigits)
        goal_score = round(balls_collected * mult, ndigits)

    # ----- In-process scoring -----
    in_proc_total = 0.0
    for x in range(1, in_process_balls + 1):
        y = 50 * math.exp(-(x ** 2) / (2 * (20 ** 2)))
        in_proc_total += y

    in_proc_score = round(in_proc_total, ndigits)

    # ----- Final total -----
    return round(goal_score + in_proc_score, ndigits)
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
        "total",
        "delta",
        "ipoints",                # *** NEW ***
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

# ====================== GAME STATE ============================

state = {
    "current_iteration": 1,
    "plan_number": 0,
    "ball_count": 0,
    "is_counting": False,
    "iterations_data": [],
    "number_of_players": 0,
    "csv_timestamp": None
}

state_lock = threading.Lock()
updates_q = queue.Queue()

def reset_arduino():
    pass

button = None

# ======================== ROUTES ===============================


@app.route('/')
def dashboard():
    return render_template(
        'dashboard.html',
        current_iteration=state["current_iteration"],
        plan_number=state["plan_number"],
        iterations_data=state["iterations_data"],
        number_of_players=state["number_of_players"]
    )



@app.route('/set_players', methods=['POST'])
def set_players():
    players = request.json.get('players', 0)
    state["number_of_players"] = players
    return jsonify({"success": True})


@app.route('/set_plan', methods=['POST'])
def set_plan():
    plan = request.json.get('plan', 0)
    state["plan_number"] = plan
    return jsonify({"success": True})

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
    
    return jsonify({"success": True})

@app.route('/stop_iteration', methods=['POST'])
def stop_iteration():
    state["is_counting"] = False
    return jsonify({"success": True, "final_count": state["ball_count"]})


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

    balls_collected = actual
    goal_target = plan
    in_process_balls = in_progress

    # Use your scoring function
    final_score = compute_score(
        balls_collected,
        goal_target,
        in_process_balls
    )
    ipoints = final_score

    iteration_data = {
        "iteration": state["current_iteration"],
        "plan": plan,
        "actual": actual,
        "defects": defects,
        "in_progress": in_progress,
        "total": total,
        "delta": delta,
        "ipoints": ipoints,
        "timestamp": datetime.now().isoformat(),
        "team_players": state["number_of_players"],
    }

    with state_lock:
        state["iterations_data"].append(iteration_data)
        num_iters = len(state["iterations_data"])

        if state["current_iteration"] < 5:
            state["current_iteration"] += 1

    if num_iters in (3, 5):
        save_iterations_to_csv()

    return jsonify({
        "success": True,
        "iteration_data": iteration_data,
        "current_iteration": state["current_iteration"]
    })   


@app.route('/get_current_count')

def get_current_count():
    return jsonify({"count": state["ball_count"]})

@app.route('/get_final_results')

def get_final_results():
    return jsonify({
        "success": True, #maybe remove
        "iterations_data": state["iterations_data"],
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
                time.sleep(1)
                yield "event: status\ndata: idle\n\n"
                continue
            try:
                cnt = updates_q.get(timeout=15)
                yield f"data: {cnt}\n\n"

            except queue.Empty:
                yield "event: ping\ndata: keep-alive\n\n"
    return Response(stream(), mimetype="text/event-stream")


@app.route('/reset_system', methods=['POST'])

def reset_system():
    state["current_iteration"] = 1
    state["plan_number"] = 0
    state["ball_count"] = 0
    state["is_counting"] = False
    state["iterations_data"] = []
    state["number_of_players"] = 0
    state["csv_timestamp"] = None
    return jsonify({"success": True})

# ===================== GPIO INIT ===============================

def init_gpio_once():
    global button

    if not GPIO_OK:
        print("GPIO not available — web-only mode.")
        return

    def on_press():
        with state_lock:
            if not state["is_counting"]:
                return

            state["ball_count"] += 1
            new_cnt = state["ball_count"]

        updates_q.put(new_cnt)
        print(f"Count: {new_cnt}")

    button = Button(SW_PIN, pull_up=True, bounce_time=DEBOUNCE)
    button.when_pressed = on_press
    print("GPIO17 initialized with debounce=20ms")

# ======================= MAIN =================================

if __name__ == '__main__':
    try:
        init_gpio_once()
    except Exception as e:
        print("GPIO init failed:", e)
    print("Starting Agile Game Server...")
    print("Access at: http://localhost:5000")

    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
