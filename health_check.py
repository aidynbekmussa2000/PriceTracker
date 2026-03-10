import requests

markets = [
    "https://arbuz.kz",
    "https://marco.kz",
    "https://vprestige.kz",
    "https://tomas.kz",
    "https://jmart.kz",
    "https://abdi.kz",
    "https://depot.kz",
    "https://megastroy.kz",
    "https://twelve.kz",
    "https://europharma.kz",
    "https://newauto.kz",
    "https://komfort.kz",
    "https://shoptelecom.kz",
    "https://fmobile.kz",
    "https://astykzhan.kz",
    "https://meloman.kz",
    "https://vkusmart.kz",
    "https://oe.kz",
    "https://sulpak.kz",
    "https://finn-flare.kz",
    "https://findhow.kz",
    "https://tele2.kz",
    "https://kaspi.kz",
    "https://mycar.kz",
    "https://kingfisher.kz",
    "https://i-teka.kz",
    "https://imperiacvetov.kz",
    "https://domsad.kz",
    "https://ayanmarket.kz",
    "https://krisha.kz",
    "https://restolife.kz",
    "https://semeiny.kz",
    "https://biosfera.kz",
    "https://leader.kz",
    "https://instashop.kz",
    "https://flip.kz",
    "https://mebel.kz",
    "https://lamoda.kz",
    "https://markformelle.kz",
    "https://intertop.kz",
    "https://bankchart.kz",
    "https://edostavka.kz",
    "https://emoda.kz",
    "https://greenwich.kz",
    "https://volna.kz"
]

for url in markets:
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"{url} is reachable.")
        else:
            print(f"{url} returned status code {response.status_code}.")
    except requests.RequestException as e:
        print(f"Error reaching {url}: {e}")