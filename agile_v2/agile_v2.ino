int switch_balls = 0;
int touchState = 0;
int lastTouchState = 0;

void setup() {
    pinMode(A0, INPUT);
    Serial.begin(9600);
    Serial.println("Arduino Ready");
}

void loop() {
    // Check if a reset command is received
    if (Serial.available() > 0) {
        char command = Serial.read();
        if (command == 'r') {
            switch_balls = 0;  // Reset counter
            Serial.println("Counter reset to 0");  // Confirm reset
        }
    }

    // Read touch sensor and count
    touchState = analogRead(A0) > 10 ? 1 : 0;
    if (lastTouchState == 1 && touchState == 0) {
        switch_balls++;
    }
    lastTouchState = touchState;

    // Continuously send the counter value to Python
    Serial.println(switch_balls);
    
    delay(50);  // Adjust for a smooth, real-time update rate
}
