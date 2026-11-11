from integrations.wapenda import send_whatsapp_message

result = send_whatsapp_message(
    to="254798306373",
    text="test"
)

print(result)