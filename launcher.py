import subprocess
import sys
import time
import os

def main():
    print("===================================================")
    print("    INICIANDO QUANT TRADER SYSTEM (BOT + DASH)     ")
    print("===================================================")
    
    # Obtener el directorio donde está este script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Rutas a los scripts
    server_script = os.path.join(base_dir, "dashboard", "server.py")
    bot_script = os.path.join(base_dir, "main_vwap.py")
    
    # Iniciar servidor del dashboard en segundo plano
    print("[*] Iniciando Dashboard Server...")
    server_process = subprocess.Popen([sys.executable, server_script])
    
    # Esperar 2 segundos para dar tiempo a que el servidor levante
    time.sleep(2)
    
    # Iniciar motor de trading
    print("[*] Iniciando Trading Bot (main_vwap.py)...")
    bot_process = subprocess.Popen([sys.executable, bot_script])
    
    print("\n[+] Todo el sistema está corriendo. Presiona Ctrl+C para detener todo.\n")
    
    try:
        # Mantener el launcher vivo y monitorear los procesos
        while True:
            time.sleep(1)
            
            # Si alguno de los procesos muere inesperadamente, notificamos
            if server_process.poll() is not None:
                print("\n[!] ADVERTENCIA: El servidor del dashboard se ha detenido.")
                break
                
            if bot_process.poll() is not None:
                print("\n[!] ADVERTENCIA: El motor de trading se ha detenido.")
                break
                
    except KeyboardInterrupt:
        print("\n\n[!] Señal de apagado recibida (Ctrl+C). Deteniendo procesos...")
        
    finally:
        # Asegurarnos de matar los procesos hijos si cerramos el launcher
        print("[*] Cerrando servidor...")
        if server_process.poll() is None:
            server_process.terminate()
            
        print("[*] Cerrando bot de trading...")
        if bot_process.poll() is None:
            bot_process.terminate()
            
        print("[+] Sistema apagado correctamente.")

if __name__ == "__main__":
    main()
