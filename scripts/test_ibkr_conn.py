from ib_insync import *
import time

def test_conn():
    print("🚀 Démarrage du test de connexion IBKR...")
    
    # 1. Setup
    ib = IB()
    
    # 2. Connection (Port 4002 for Paper)
    try:
        print("🔌 Tentative de connexion sur 127.0.0.1:4002...")
        ib.connect('127.0.0.1', 4002, clientId=999)
        print("✅ CONNEXION RÉUSSIE !")
        
        # 3. Check Account
        print("\n🔍 Vérification du compte...")
        account_summary = ib.accountSummary()
        
        found_cash = False
        for val in account_summary:
            if val.tag == 'TotalCashValue':
                print(f"💰 Cash Disponible : {val.value} {val.currency}")
                found_cash = True
                
        if not found_cash:
            print("⚠️ Impossible de lire le Cash (Vérifie 'Read-Only API' désactivé ?)")

        # 4. Disconnect
        ib.disconnect()
        print("\n👋 Déconnecté proprement.")
        
    except Exception as e:
        print(f"\n❌ ERREUR DE CONNEXION : {e}")
        print("\n💡 SOLUTIONS :")
        print("1. Vérifie dans IB Gateway > File > Global Configuration > API > Settings")
        print("   -> 'Enable ActiveX and Socket Clients' doit être COCHÉ")
        print("   -> 'Read-Only API' doit être DÉCOCHÉ (IMPORTANT !)")
        print("   -> 'Socket Port' doit être 4002")

if __name__ == '__main__':
    test_conn()
