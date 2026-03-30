from nlp_service import intent_classifier

print('Testing intent classification...')
test_messages = [
    'Hello',
    'What is diversity?',
    'How to promote inclusion?',
    'Goodbye',
    'Tell me about equity'
]

for msg in test_messages:
    intent = intent_classifier.predict(msg)
    print(f'{msg} -> {intent}')
