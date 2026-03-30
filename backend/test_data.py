import csv

try:
    with open('data/diversity_equity_inclusion_data.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        data = list(reader)
        print(f'Loaded {len(data)} rows')
        if data:
            print('First row keys:', list(data[0].keys()))
            print('First row sample:', data[0])
        else:
            print('No data loaded')
except Exception as e:
    print(f'Error loading data: {e}')
