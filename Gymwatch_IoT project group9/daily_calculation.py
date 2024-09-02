import json
import pandas as pd
from collections import defaultdict

# Funzione per leggere il file e restituire i dati
def read_food_log(file_path):
    daily_totals = defaultdict(lambda: {'calories': 0, 'carbs': 0, 'fats': 0, 'proteins': 0})
    
    with open(file_path, 'r') as file:
        for line in file:
            # Carica la riga come un dizionario
            food_entry = json.loads(line.strip())
            
            # Estrai le informazioni
            date = food_entry.get('date')
            calories = food_entry.get('kcal', 0)
            carbs = food_entry.get('carbs', 0)
            fats = food_entry.get('fats', 0)
            proteins = food_entry.get('proteins', 0)
            
            # Aggiorna i totali giornalieri
            daily_totals[date]['calories'] += calories
            daily_totals[date]['carbs'] += carbs
            daily_totals[date]['fats'] += fats
            daily_totals[date]['proteins'] += proteins
    
    return daily_totals

# Funzione per esportare i dati in un file Excel
def export_to_excel(daily_totals, output_file):
    # Converti i dati in un DataFrame
    df = pd.DataFrame.from_dict(daily_totals, orient='index').reset_index()
    df.rename(columns={'index': 'Date'}, inplace=True)
    
    # Esporta il DataFrame in un file Excel
    df.to_excel(output_file, index=False)

# Funzione per stampare i risultati
def print_daily_totals(daily_totals):
    for date, totals in sorted(daily_totals.items()):
        print(f"Date: {date}")
        print(f"  Total Calories: {totals['calories']:.2f}")
        print(f"  Total Carbs: {totals['carbs']:.2f} g")
        print(f"  Total Fats: {totals['fats']:.2f} g")
        print(f"  Total Proteins: {totals['proteins']:.2f} g")
        print()

# Main
if __name__ == '__main__':
    file_path = 'food_log.txt'  # Inserisci il percorso del file
    output_file = 'food_log_summary.xlsx'  # Nome del file Excel di output
    daily_totals = read_food_log(file_path)
    print_daily_totals(daily_totals)
    export_to_excel(daily_totals, output_file)
    print(f'Dati esportati in {output_file}')
