import flet as ft
import csv
import threading
import os
import re
import json
import ssl
import urllib.request
import platform
from io import StringIO

# --- CONFIGURACIÓN ---
URL_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRX2MAGIFlkpTm_SE2kVwKt7CwPR4xhaPnWFOh5TOWdykxfT8N1QGJru4aoBD6W9R5udYGew4VyetFH/pub?gid=983288468&single=true&output=csv"
CACHE_FILE = "andromeda_db.json"
STORAGE_FOLDER = "Andromeda_Files"

# Asegurar carpeta de archivos
if not os.path.exists(STORAGE_FOLDER):
    try: os.makedirs(STORAGE_FOLDER)
    except: pass

class AndromedaApp:
    def __init__(self):
        self.data = []
        self.jerarquia = {}
        self.ruta_actual = []
        self.syncing = False

    def safe_str(self, val): return str(val).strip() if val else ""

    def extraer_id_drive(self, link_raw):
        link = self.safe_str(link_raw)
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
        return match.group(1) if match else link

    def inferir_metadatos(self, nombre_archivo):
        nombre = self.safe_str(nombre_archivo).upper()
        area = "General"
        match_area = re.search(r'-(\d{4})[-_]', nombre)
        if match_area: area = f"Área {match_area.group(1)}"
        elif "1002" in nombre: area = "Área 1002"
        
        tipo = "Doc"
        if any(x in nombre for x in ["DW", "PLANO"]): tipo = "Plano"
        elif any(x in nombre for x in ["TS", "ET"]): tipo = "Espec. Téc."
        elif any(x in nombre for x in ["MC", "MEMORIA"]): tipo = "Memoria"
        return area, tipo

    def get_local_path(self, nombre_archivo):
        nombre_clean = re.sub(r'[\\/*?:"<>|]', "", nombre_archivo)
        if not nombre_clean.lower().endswith(".pdf"): nombre_clean += ".pdf"
        # Usamos rutas relativas para máxima compatibilidad en Android
        return os.path.join(STORAGE_FOLDER, nombre_clean)

    def procesar_csv(self, csv_text):
        f = StringIO(csv_text)
        reader = csv.DictReader(f, fieldnames=["col_archivo", "col_link", "col_nombre_real"])
        processed = []
        for row in reader:
            nombre = self.safe_str(row.get("col_archivo"))
            link = self.safe_str(row.get("col_link"))
            if not nombre or "nombre" in nombre.lower(): continue
            drive_id = self.extraer_id_drive(link)
            if not drive_id: continue
            
            area, tipo = self.inferir_metadatos(nombre)
            titulo = self.safe_str(row.get("col_nombre_real"))
            if not titulo or titulo == "#N/A": titulo = nombre

            processed.append({
                "id": drive_id,
                "titulo": titulo,
                "nombre_archivo": nombre,
                "area": area,
                "tipo": tipo,
                "path": self.get_local_path(nombre)
            })
        return processed

    def construir_jerarquia(self):
        nueva_jerarquia = {}
        for doc in self.data:
            area = doc["area"]
            tipo = doc["tipo"]
            if area not in nueva_jerarquia: nueva_jerarquia[area] = {"_count": 0, "_sub": {}}
            if tipo not in nueva_jerarquia[area]["_sub"]: nueva_jerarquia[area]["_sub"][tipo] = {"_count": 0, "_docs": []}
            nueva_jerarquia[area]["_sub"][tipo]["_docs"].append(doc)
            nueva_jerarquia[area]["_sub"][tipo]["_count"] += 1
            nueva_jerarquia[area]["_count"] += 1
        self.jerarquia = nueva_jerarquia

def main(page: ft.Page):
    app = AndromedaApp()
    page.title = "Andrómeda"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#111111"
    page.padding = 15

    # --- UI ELEMENTS ---
    lbl_status = ft.Text("Listo", size=12, color="grey")
    pb = ft.ProgressBar(width=400, color="blue", visible=False)
    lista_ui = ft.Column(scroll="auto", expand=True)

    def actualizar_ui():
        lista_ui.controls.clear()
        
        # Botón Volver
        if app.ruta_actual:
            lista_ui.controls.append(
                ft.TextButton("< Volver", on_click=volver_atras, icon=ft.icons.ARROW_BACK)
            )
            lista_ui.controls.append(ft.Text(" / ".join(app.ruta_actual), size=14, color="blue", weight="bold"))

        nivel = len(app.ruta_actual)
        
        if not app.data:
            lista_ui.controls.append(ft.Container(
                content=ft.Text("No hay datos locales. Presiona SYNC.", color="orange", text_align="center"),
                padding=20
            ))
        elif nivel == 0: # Áreas
            for area in sorted(app.jerarquia.keys()):
                lista_ui.controls.append(ft.ListTile(
                    leading=ft.Icon(ft.icons.FOLDER, color="amber"),
                    title=ft.Text(area),
                    subtitle=ft.Text(f"{app.jerarquia[area]['_count']} documentos"),
                    on_click=lambda e, a=area: navegar(a)
                ))
        elif nivel == 1: # Tipos
            area = app.ruta_actual[0]
            sub = app.jerarquia[area]["_sub"]
            for tipo in sorted(sub.keys()):
                lista_ui.controls.append(ft.ListTile(
                    leading=ft.Icon(ft.icons.FOLDER_OPEN, color="blue"),
                    title=ft.Text(tipo),
                    subtitle=ft.Text(f"{sub[tipo]['_count']} archivos"),
                    on_click=lambda e, t=tipo: navegar(t)
                ))
        elif nivel == 2: # Documentos
            area, tipo = app.ruta_actual[0], app.ruta_actual[1]
            docs = app.jerarquia[area]["_sub"][tipo]["_docs"]
            for d in docs:
                descargado = os.path.exists(d["path"])
                lista_ui.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.icons.DESCRIPTION, color="green" if descargado else "grey"),
                        ft.Column([
                            ft.Text(d["titulo"], size=14, weight="bold", width=250),
                            ft.Text("Disponible Offline" if descargado else "Pendiente de descarga", size=11, color="grey")
                        ], expand=True),
                        ft.IconButton(ft.icons.OPEN_IN_NEW, on_click=lambda e, doc=d: abrir_doc(doc))
                    ]),
                    padding=10, bgcolor="#222222", border_radius=8
                ))
        page.update()

    def navegar(destino):
        app.ruta_actual.append(destino)
        actualizar_ui()

    def volver_atras(e):
        if app.ruta_actual: app.ruta_actual.pop()
        actualizar_ui()

    def abrir_doc(doc):
        if os.path.exists(doc["path"]):
            # En Android usamos el path absoluto para abrir
            abs_path = os.path.abspath(doc["path"])
            page.launch_url(f"file://{abs_path}")
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Archivo no descargado. Pulsa SYNC."))
            page.snack_bar.open = True
            page.update()

    def iniciar_sync(e):
        if app.syncing: return
        threading.Thread(target=ejecutar_sync, daemon=True).start()

    def ejecutar_sync():
        app.syncing = True
        btn_sync.disabled = True
        pb.visible = True
        pb.value = None
        lbl_status.value = "Conectando con Drive..."
        page.update()

        try:
            # 1. Bajar lista
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(URL_CSV, context=context) as response:
                csv_data = response.read().decode('utf-8')
                app.data = app.procesar_csv(csv_data)
                app.construir_jerarquia()
                # Guardar caché
                with open(CACHE_FILE, 'w') as f: json.dump(app.data, f)
            
            actualizar_ui()

            # 2. Descargar archivos faltantes
            total = len(app.data)
            for i, doc in enumerate(app.data):
                if not os.path.exists(doc["path"]):
                    lbl_status.value = f"Bajando {i+1}/{total}: {doc['nombre_archivo'][:20]}..."
                    pb.value = (i+1)/total
                    page.update()
                    try:
                        url = f"https://drive.google.com/uc?export=download&id={doc['id']}"
                        with urllib.request.urlopen(url, context=context) as resp, open(doc["path"], 'wb') as out:
                            out.write(resp.read())
                    except: pass
            
            lbl_status.value = "Sincronización Completa ✅"
        except Exception as ex:
            lbl_status.value = f"Error: {str(ex)}"
        
        app.syncing = False
        btn_sync.disabled = False
        pb.visible = False
        actualizar_ui()

    # --- CARGA INICIAL ---
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                app.data = json.load(f)
                app.construir_jerarquia()
                lbl_status.value = "Datos cargados desde memoria"
        except: pass

    btn_sync = ft.ElevatedButton("SYNC TOTAL 🔄", on_click=iniciar_sync, bgcolor="blue", color="white")
    
    page.add(
        ft.Column([
            ft.Text("ANDRÓMEDA", size=24, weight="bold"),
            btn_sync,
            pb,
            lbl_status,
            ft.Divider(),
            lista_ui
        ], expand=True)
    )
    actualizar_ui()

if __name__ == "__main__":
    ft.app(target=main)
