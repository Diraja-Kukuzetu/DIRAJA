from integrations.wapenda import send_whatsapp_message

result = send_whatsapp_message(
    to="254780435700",
    text="Test notification message from Dira"
)

print(result)