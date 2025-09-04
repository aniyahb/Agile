int switch_balls = 0;  // A counter that tracks the number of times the touch sensor is activated.
int touchState = 0;  // The current state of the touch sensor (1 for touched, 0 for not touched).
int lastTouchState = 0; // The previous state of the touch sensor, used to detect state changes.

void setup() {
    pinMode(A0, INPUT);  // Configures pin A0 as an input to read the touch sensor.
    Serial.begin(9600);  // Initializes serial communication at a baud rate of 9600 bits per second.
    Serial.println("Arduino Ready");   // Sends a message to the Serial Monitor to indicate that the Arduino is ready.
}

void loop() {
    // Check if a reset command is received
    if (Serial.available() > 0) {     // Checks if there is data available to read from the Serial Monitor.
        char command = Serial.read();   // Reads the incoming character.
        if (command == 'r') {
            switch_balls = 0;  // Resets the counter to 0 if the received character is 'r'.
            Serial.println("Counter reset to 0");  // Sends a confirmation message to the Serial Monitor.
        }
    }

    // Read touch sensor and count
    touchState = analogRead(A0) > 10 ? 1 : 0;  // Reads the analog value from pin A0 (range: 0–1023). If the value is greater than 10, it sets touchState to 1 (touched); otherwise, it sets it to 0 (not touched).
    if (lastTouchState == 1 && touchState == 0) {   // Detects a transition from touched (1) to not touched (0).
        switch_balls++; // Updates the previous state for the next iteration.
    }
    lastTouchState = touchState;   // Updates the previous state for the next iteration.

    Serial.println(switch_balls); // Sends the current value of switch_balls to the Serial Monitor for real-time updates.
    
    delay(50);  // Adjust for a smooth, real-time update rate
}
