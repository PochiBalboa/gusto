"""
gusto_scraper.py
-----------------
Recolecta menciones REALES y públicas de la palabra "gusto" para alimentar
el proyecto tipo "We Feel Fine". Pensado para correr en TU máquina/servidor,
no en el sandbox de Claude (que no tiene salida de red hacia estos sitios).

Fuentes incluidas:
  1) Reddit  -> usa la API OFICIAL de Reddit vía OAuth (librería praw).
     Reddit bloquea (403) los pedidos anónimos al buscador público desde
     2023, así que hace falta una cuenta de "app" gratuita — ver instrucciones
     en el paso "Cómo conseguir client_id y client_secret" más abajo.
  2) Mercado Libre -> usa la API pública de reseñas por ID de producto
     (api.mercadolibre.com/reviews/item/{ITEM_ID}). Requiere que vos le pases
     el ID del producto que te interesa (no hay forma de "buscar en todo
     Mercado Libre" sin su API de catálogo autenticada).

Cómo conseguir client_id y client_secret (gratis, 2 minutos):
    1. Entrá a https://www.reddit.com/prefs/apps con tu cuenta de Reddit.
    2. Click en "create app" / "create another app" (abajo de todo).
    3. Nombre: el que quieras (ej: gusto-almanaque). Tipo: elegí "script".
    4. En "redirect uri" poné: http://localhost:8080
    5. Click "create app". Te va a aparecer un cuadro con dos datos:
       - un código corto abajo de "personal use script" -> ese es tu client_id
       - un campo que dice "secret" -> ese es tu client_secret

Uso:
    pip install requests praw
    python gusto_scraper.py --reddit --client-id TU_CLIENT_ID --client-secret TU_CLIENT_SECRET --hours 24
    python gusto_scraper.py --meli MLA1234567890

Salida: gusto_data.json — lista de menciones con texto, fuente, fecha y
categoría estimada (comida / música / gente / vida / otro), lista para
alimentar la página web del prototipo.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

HEADERS = {"User-Agent": "gusto-almanaque-research/0.1 (uso personal, no comercial)"}
OUT_FILE = Path("data.json")

# Clasificación simple por palabras clave. Ajustá las listas a gusto (nunca mejor dicho).
CATEGORY_KEYWORDS = {
    "comida": ["comida", "comer", "receta", "asado", "sabor", "plato", "cocina", "dulce", "salado"],
    "musica": ["canción", "cancion", "disco", "banda", "tema", "playlist", "música", "musica", "recital"],
    "gente": ["conocer", "conocerte", "persona", "che", "amigo", "compañero", "compañía", "equipo"],
    "vida": ["vida", "viajar", "carrera", "trabajo", "decisión", "decision", "casa", "vivir"],
}


def guess_category(text: str) -> str:
    lowered = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in lowered for w in words):
            return cat
    return "otro"


def fetch_reddit(subreddits, hours, client_id, client_secret, query="gusto"):
    """Busca posts recientes que mencionen `query` en los subreddits dados,
    usando la API oficial de Reddit (OAuth) en vez del endpoint público
    anónimo, que Reddit bloquea con 403 desde 2023."""
    try:
        import praw
    except ImportError:
        print("  [!] Falta instalar praw. Corré: pip install praw")
        return []

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=HEADERS["User-Agent"],
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = []
    for sub in subreddits:
        sub = sub.strip()
        try:
            submissions = reddit.subreddit(sub).search(query, sort="new", time_filter="week", limit=100)
            for post in submissions:
                created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if created < cutoff:
                    continue
                text = (post.title + " — " + (post.selftext or "")).strip()
                if query.lower() not in text.lower():
                    continue
                results.append({
                    "source": "reddit",
                    "subreddit": sub,
                    "text": text[:400],
                    "url": f"https://reddit.com{post.permalink}",
                    "created_utc": created.isoformat(),
                    "category": guess_category(text),
                })
        except Exception as e:
            print(f"  [!] error buscando en r/{sub}: {e}")
            continue
        time.sleep(1)  # prudente con el rate limit
    return results


def fetch_meli_reviews(item_id):
    """Trae reseñas públicas de un producto puntual de Mercado Libre."""
    url = f"https://api.mercadolibre.com/reviews/item/{item_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] error consultando reseñas de {item_id}: {e}")
        return []

    data = resp.json()
    results = []
    for review in data.get("reviews", []):
        text = (review.get("title", "") + " — " + review.get("content", "")).strip()
        if "gusto" not in text.lower():
            continue
        results.append({
            "source": "mercadolibre",
            "item_id": item_id,
            "text": text[:400],
            "rate": review.get("rate"),
            "date": review.get("date"),
            "category": guess_category(text),
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Recolector real de menciones de 'gusto'")
    parser.add_argument("--reddit", action="store_true", help="buscar en Reddit")
    parser.add_argument("--subreddits", default="argentina,AskArgentina,es,mexico,vzla",
                         help="lista separada por comas")
    parser.add_argument("--hours", type=int, default=24, help="ventana de tiempo en horas")
    parser.add_argument("--client-id", default=os.environ.get("REDDIT_CLIENT_ID"),
                         help="client_id de tu app de Reddit (o variable de entorno REDDIT_CLIENT_ID)")
    parser.add_argument("--client-secret", default=os.environ.get("REDDIT_CLIENT_SECRET"),
                         help="client_secret de tu app de Reddit (o variable de entorno REDDIT_CLIENT_SECRET)")
    parser.add_argument("--meli", nargs="*", default=[], help="IDs de producto de Mercado Libre, ej: MLA1234567890")
    args = parser.parse_args()

    all_results = []

    if args.reddit:
        if not args.client_id or not args.client_secret:
            print("  [!] Para usar --reddit hace falta --client-id y --client-secret")
            print("      (por argumento, o como variables de entorno REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET).")
        else:
            print("Buscando en Reddit...")
            all_results += fetch_reddit(args.subreddits.split(","), args.hours, args.client_id, args.client_secret)

    for item_id in args.meli:
        print(f"Buscando reseñas de {item_id}...")
        all_results += fetch_meli_reviews(item_id)

    if not all_results:
        print("No se encontraron menciones nuevas (o no pasaste --reddit / --meli). No se toca data.json.")
        return

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": all_results,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nListo: {len(all_results)} menciones guardadas en {OUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
