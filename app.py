from flask import Flask, render_template, request, jsonify,redirect, url_for
import serial
import time

app = Flask(__name__)

# Store state
state = {
    "balls_counter": 0,
    "metrics": "",
    "strategy": "",
    "current_round": 1,
    "allRoundsData": []
}


def reset_arduino():
    """ Sends a command to reset the switch_balls counter to 0 and updates Python state. """
    try:
        arduino = serial.Serial(port='COM7', baudrate=9600, timeout=1)
        time.sleep(2)  # Allow connection to stabilize
        arduino.write(b'r')  # Send reset command
        time.sleep(1)  # Give Arduino time to reset

        response = arduino.readline().decode().strip()  # Read confirmation
        print(f"Arduino response: {response}")

        if "Counter reset to 0" in response:
            state["balls_counter"] = 0  # Ensure Python knows the counter is reset
            print("Python state updated: balls_counter = 0")

        arduino.close()
    except serial.SerialException as e:
        print(f"Error: {e}")
def get_arduino_connection():
    try:
        arduino = serial.Serial(port='COM7', baudrate=9600, timeout=1)
        time.sleep(2)  # Allow Arduino to initialize
        print("Arduino connected successfully!")
        return arduino
    except Exception as e:
        print(f"Error connecting to Arduino: {e}")
        return None


@app.route('/')
@app.route('/plan')
def plan():
    return render_template('plan.html', current_round=state["current_round"])



@app.route('/timer', methods=['GET', 'POST'])
def timer():
    if request.method == 'POST':
        plan_value = request.form.get('plan_value')

        if not plan_value or not plan_value.isdigit():
            return render_template('plan.html', current_round=state["current_round"], error="Invalid input for plan_value")

        plan_value = int(plan_value)

        # Store plan value for this round
        existing_round = next((r for r in state["allRoundsData"] if r["round"] == state["current_round"]), None)
        if existing_round:
            existing_round["plan"] = plan_value
        else:
            state["allRoundsData"].append({
                "round": state["current_round"],
                "plan": plan_value,
                "total": 0,
                "defects": 0
            })

        print(f"DEBUG: Plan value set to {plan_value}, redirecting to Timer")
        return redirect(url_for('timer'))  # Redirect to GET /timer after setting plan

    return render_template('timer.html', balls_counter=state["balls_counter"], current_round=state["current_round"])


@app.route('/update_counter', methods=['GET'])
def update_counter():
    arduino = get_arduino_connection()
    if arduino:
        try:
            response = arduino.readline().decode().strip()
            if response.isdigit():
                state["balls_counter"] = int(response)
                return jsonify({"balls_counter": state["balls_counter"]})
        except Exception as e:
            print(f"Error fetching live counter: {e}")
        finally:
            arduino.close()

    return jsonify({"error": "Failed to connect to Arduino"}), 500


@app.route('/get_round_data/<int:round_number>')
def get_round_data(round_number):
    round_data = next((data for data in state["allRoundsData"] if data["round"] == round_number), None)
    if round_data:
        actual = round_data["total"] - round_data["defects"]
        delta = actual - round_data["plan"]
        return jsonify({
            "plan": round_data["plan"],
            "total": round_data["total"],
            "defects": round_data["defects"],
            "actual": actual,
            "delta": delta
        })
    return jsonify({"error": "Round not found"}), 404

@app.route('/defects', methods=['GET'])
def defects():
    last_round = next((r for r in state["allRoundsData"] if r["round"] == state["current_round"]), None)
    defects = last_round["defects"] if last_round else 0
    return render_template('defects.html', current_round=state["current_round"], defects=defects)

@app.route('/update_defects', methods=['POST'])
def update_defects():
    defects_value = request.form.get('defects')

    if not defects_value or not defects_value.isdigit():
        return jsonify({"error": "Invalid defects value"}), 400

    defects_value = int(defects_value)

    for round_data in state["allRoundsData"]:
        if round_data["round"] == state["current_round"]:
            round_data["defects"] = defects_value
            break

    return jsonify({"message": "Defects updated", "allRoundsData": state["allRoundsData"]})

@app.route('/metric', methods=['GET', 'POST'])
def metric():
    state["metrics"] = f"Calculated Value: {state['balls_counter'] * 2}"

    # Debugging prints to verify if data is passed
    print("DEBUG: Passing to metric.html")
    print("DEBUG: Current Round:", state["current_round"])
    print("DEBUG: All Rounds Data:", state["allRoundsData"])

    return render_template(
        'metric.html',
        metrics=state["metrics"],
        current_round=state["current_round"],
        allRoundsData=state["allRoundsData"]
    )


@app.route('/strategize')
def strategize_page():
    reset_arduino()
    return render_template('strategize.html', current_round=state["current_round"],
                           allRoundsData=state["allRoundsData"])


@app.route('/next_round', methods=['POST'])
def next_round():
    plan_value = request.form.get('plan_value')

    if not plan_value or not plan_value.isdigit():
        print("DEBUG: Invalid plan value received")  # Debugging output
        return jsonify({"error": "Invalid plan value"}), 400

    plan_value = int(plan_value)

    # Check if the round already exists before adding
    existing_round = next((r for r in state["allRoundsData"] if r["round"] == state["current_round"]), None)

    if existing_round:
        print(f"DEBUG: Round {state['current_round']} already exists, skipping duplicate append.")
    else:
        new_round_data = {
            "round": state["current_round"],
            "plan": plan_value,
            "total": state["balls_counter"],
            "defects": 0
        }
        state["allRoundsData"].append(new_round_data)

    state["current_round"] += 1
    print("DEBUG: Current Rounds Data:", state["allRoundsData"])  # Debugging output

    return jsonify({"current_round": state["current_round"], "allRoundsData": state["allRoundsData"]})


@app.route('/clear_data', methods=['POST'])
def clear_data():
    state["current_round"] = 1
    return jsonify({"message": "Data cleared", "current_round": state["current_round"]})


@app.route('/update_round', methods=['POST'])
def update_round():
    plan_value = request.form.get('plan_value')
    total_count = state["balls_counter"]

    if not plan_value or not plan_value.isdigit():
        return jsonify({"error": "Invalid plan value"}), 400

    plan_value = int(plan_value)

    # Check if the round already exists, update instead of appending
    for round_data in state["allRoundsData"]:
        if round_data["round"] == state["current_round"]:
            round_data["plan"] = plan_value
            round_data["total"] = total_count
            print(f"DEBUG: Updated Round {state['current_round']} instead of duplicating.")
            return jsonify({"message": "Round updated", "allRoundsData": state["allRoundsData"]})

    # If the round doesn't exist, create a new entry (only if necessary)
    new_round_data = {
        "round": state["current_round"],
        "plan": plan_value,
        "total": total_count,
        "defects": 0  # Keeping it fixed for now
    }
    state["allRoundsData"].append(new_round_data)

    print("DEBUG: Round appended:", state["allRoundsData"])  # Debugging output
    return jsonify({"message": "Round added", "allRoundsData": state["allRoundsData"]})

from flask import Response, stream_with_context

@app.route('/live_counter')
def live_counter():
    def stream():
        arduino = get_arduino_connection()
        if arduino:
            try:
                while True:
                    response = arduino.readline().decode().strip()  # Read live data
                    if response.isdigit():
                        state["balls_counter"] = int(response)
                        yield f"data: {state['balls_counter']}\n\n"  # Send event data
            except Exception as e:
                print(f"Error fetching live counter: {e}")
            finally:
                arduino.close()

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


if __name__ == '__main__':
    app.run(debug=True)
