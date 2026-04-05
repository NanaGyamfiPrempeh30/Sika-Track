"""Quick test script to see what the parser returns for various inputs."""
from bot.parser import parse_message  # Import our parser function

# List of test messages to try
test_inputs = [
    "sold 50",          # Sale without category
    "sold 200 kenkey",  # Sale with category
    "spent 30 gas",     # Expense with category
    "summary",          # Summary request
    "hello world",      # Unknown message
]

# Loop through each test and print the result
for msg in test_inputs:
    result = parse_message(msg)  # Parse the message
    print(f"'{msg}' -> {result}")  # Show input and output
