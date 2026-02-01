import flet as ft
import csv
import threading
import os
import re
import json
import ssl
import urllib.request
from io import StringIO

# --- CONFIGURACIÓN ---
URL_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRX2MAGIFlkpTm_SE2kVwKt7CwPR4xhaPnWFOh5TOWdykxfT8N1QGJru4aoBD6W9R5udYGew4VyetFH/pub?gid=983288468&single=true&output=csv"
CACHE_FILE = "andromeda_db.json"
STORAGE_FOLDER = "Andromeda_Files"

if not os.path.exists(STORAGE_FOLDER):
    try: os.makedirs(STORAGE_FOLDER)
    except: pass

class AndromedaApp:
    def __init__(self):
        self.data = []
        self.jerarquia = {}
        self.ruta_actual = []
        self.syncing = False

    def extraer_id_drive(self, link):
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(link))
        return match.group(1) if match else str(link)

    def inferir_metadatos(self, nombre):
        nombre = str(nombre).upper()
        area = "General"
        match_area = re.search(r'-(\d{4})[-_]', nombre)
        if match_area: area = f"Área {match_area.group(1)}"
        tipo = "Doc"
        if any(x in nombre for x in ["DW", "PLANO"]): tipo = "Plano"
        elif any(x in nombre for x in ["TS", "ET"]): tipo = "Espec. Téc."
        return area, tipo

    def procesar_csv(self, csv_text):
        f = StringIO(csv_text)
        reader = csv.DictReader(f, fieldnames=["col_archivo", "col_link", "col_nombre_real"])
        processed = []
        for row in reader:
            nombre = str(row.get("col_archivo", "")).strip()
            if not nombre or "nombre" in nombre.lower(): continue
            drive_id = self.extraer_id_drive(row.get("col_link", ""))
            area, tipo = self.inferir_metadatos(nombre)
            path = os.path.join(STORAGE_FOLDER, f"{nombre}.pdf")
            processed.append({"id": drive_id, "titulo": row.get("col_nombre_real", nombre), "path": path, "area": area, "tipo": tipo})
        return processed

    def construir_jerarquia(self):
        self.jerarquia = {}
        for d in self.data:
            a, t = d["area"], d["tipo"]
            if a not in self.jerarquia: self.jerarquia[a] = {"_sub": {}}
            if t not in self.jerarquia[a]["_sub"]: self.jerarquia[a]["_sub"][t] = {"_docs": []}
            self.jerarquia[a]["_sub"][t]["_docs"].append(d)

def main(page: ft.Page):
    app = AndromedaApp()
    page.title = "Andrómeda"
    page.theme_mode = ft.ThemeMode.DARK
    lista_ui = ft.Column(scroll="auto", expand=True)
    pb = ft.ProgressBar(visible=False, color="orange")
    lbl = ft.Text("Listo", size=12)

    def render():
        lista_ui.controls.clear()
        nivel = len(app.ruta_actual)
        if nivel > 0:
            lista_ui.controls.append(ft.TextButton("< Volver", on_click=lambda _: (app.ruta_actual.pop(), render()), icon=ft.icons.CHEVRON_LEFT))
        
        if not app.data:
            lista_ui.controls.append(ft.Container(content=ft.Text("Sin datos. Pulsa SYNC."), padding=20))
        elif nivel == 0:
            for a in sorted(app.jerarquia.keys()):
                lista_ui.controls.append(ft.ListTile(title=ft.Text(a), leading=ft.Icon(ft.icons.FOLDER_ROUNDED, color="amber"), on_click=lambda e, a=a: (app.ruta_actual.append(a), render())))
        elif nivel == 1:
            a = app.ruta_actual[0]
            for t in sorted(app.jerarquia[a]["_sub"].keys()):
                lista_ui.controls.append(ft.ListTile(title=ft.Text(t), leading=ft.Icon(ft.icons.FOLDER_OPEN_ROUNDED, color="blue"), on_click=lambda e, t=t: (app.ruta_actual.append(t), render())))
        elif nivel == 2:
            a, t = app.ruta_actual[0], app.ruta_actual[1]
            for d in app.jerarquia[a]["_sub"][t]["_docs"]:
                existe = os.path.exists(d["path"])
                lista_ui.controls.append(ft.ListTile(
                    title=ft.Text(d["titulo"]), 
                    leading=ft.Icon(ft.icons.PICTURE_AS_PDF, color="green" if existe else "grey"), 
                    on_click=lambda e, d=d: page.launch_url(f"file://{os.path.abspath(d['path'])}")
                ))
        page.update()

    def sync_task():
        app.syncing = True
        pb.visible = True
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(URL_CSV, context=ctx) as r:
                app.data = app.procesar_csv(r.read().decode('utf-8'))
                app.construir_jerarquia()
                with open(CACHE_FILE, 'w') as f: json.dump(app.data, f)
            render()
            for i, d in enumerate(app.data):
                if not os.path.exists(d["path"]):
                    lbl.value = f"Bajando {i+1}/{len(app.data)}..."
                    page.update()
                    url = f"https://drive.google.com/uc?export=download&id={d['id']}"
                    try:
                        with urllib.request.urlopen(url, context=ctx) as res, open(d["path"], 'wb') as out: out.write(res.read())
                    except: pass
            lbl.value = "Sincronizado ✅"
        except Exception as e: lbl.value = f"Error: {e}"
        pb.visible = False
        app.syncing = False
        render()

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: app.data = json.load(f); app.construir_jerarquia()
        except: pass

    page.add(
        ft.Text("ANDRÓMEDA", size=22, weight="bold"), 
        ft.ElevatedButton("SYNC TOTAL", on_click=lambda _: threading.Thread(target=sync_task, daemon=True).start(), icon=ft.icons.SYNC), 
        pb, lbl, ft.Divider(), 
        lista_ui
    )
    render()

ft.app(target=main)
