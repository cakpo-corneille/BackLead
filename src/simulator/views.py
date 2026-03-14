from django.shortcuts import render
import random


def generate_mac_address():
    """Génère une adresse MAC aléatoire au format XX:XX:XX:XX:XX:XX."""
    return ":".join([f"{random.randint(0, 255):02X}" for _ in range(6)])


def captive_portal_simulator(request):
    """
    Simule un portail captif pour tester le widget.
    
    Comportement :
    - Si ?mac= est dans l'URL → utilise cette MAC
    - Sinon → génère une MAC aléatoire
    - La public_key est gérée côté frontend (snippet HTML)
    """
    # Récupérer la MAC depuis l'URL ou en générer une nouvelle
    mac_address = request.GET.get('mac') or request.GET.get('mac_address')
    
    if not mac_address:
        mac_address = generate_mac_address()
    
    context = {
        'mac_address': mac_address,
    }
    
    return render(request, 'simulator/index.html', context)
