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

# =============================================================
app = Flask(__name__)
def save_iterations_to_csv():
    """Save CSV at iteration 3 and overwrite at iteration 5 using same timestamp"""
    results_folder = "GAME RESULTS"

    if not os.path.exists(results_folder):
        os.makedirs(results_folder)

    if state["csv_timestamp"] is None:
        state["csv_timestamp"] = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    filename = f"results_{state['csv_timestamp']}.csv"
    full_path = os.path.join(results_folder, filename)

    fieldnames = [

        "iteration", "plan", "actual", "defects", "in_progress",

        "effective_in_progress", "delta_in_process",

        "total", "delta", "ipoints", "lmax_points",

        "timestamp", "team_players"
    ]

    with open(full_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in state["iterations_data"]:
            writer.writerow(row)
    print(f"CSV saved: {full_path}")

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
    if state["is_counting"]:
        return jsonify({"error": "Already counting"}), 400

    reset_arduino()
    state["is_counting"] = True
    state["ball_count"] = 0


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
    defects = request.json.get('defects', 0)
    in_progress = request.json.get('in_progress', 0)
    actual = state["ball_count"]
    plan = state["plan_number"]
    total = actual - defects
    delta = total - plan
    effective_in_progress = min(in_progress, 20)
    delta_in_process = effective_in_progress * 0.25
    ipoints = round(delta + delta_in_process)
    lmax_points = delta + 5
   
    iteration_data = {
        "iteration": state["current_iteration"],
        "plan": plan,
        "actual": actual,
        "defects": defects,
        "in_progress": in_progress,
        "effective_in_progress": effective_in_progress,
        "delta_in_process": round(delta_in_process, 2),
        "total": total,
        "delta": delta,
        "ipoints": ipoints,
        "lmax_points": lmax_points,
        "timestamp": datetime.now().isoformat(),
        "team_players": state["number_of_players"]
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
        "iterations_data": state["iterations_data"],
        "number_of_players": state["number_of_players"]
    })

@app.route('/live_counter')
def live_counter():
    @stream_with_context
    def stream():
        yield "event: hello\ndata: connected\n\n"
        while True:
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