SYSTEM_PROMPT = "You are a precise data engineering agent..."
TASK_INSTRUCTIONS = {
    "easy": "Focus on extracting exact SKUs and Prices.",
    "medium": "Compare titles carefully. 'iPhon 15' and 'iPhone 15' are the same.",
    "hard": "Parse the quantity from the email text and apply it to the SKU."
}