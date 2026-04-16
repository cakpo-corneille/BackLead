from django.shortcuts import render, redirect
import random

def captive_portal_simulator(request):
    """
    Simule un portail captif pour tester le widget.
    
    Comportement :
    - Si ?mac= est dans l'URL → utilise cette MAC.
    - Sinon → génère une MAC aléatoire et redirige pour l'inclure dans l'URL.
    - La public_key est gérée côté frontend (snippet HTML).
    """
    # Récupérer la MAC depuis l'URL.
    mac_address = request.GET.get('mac') or request.GET.get('mac_address')
    
    # Si aucune MAC n'est dans l'URL, en générer une et rediriger.
    if not mac_address:
        # Utiliser la fonction existante du widget pour cohérence
        mac_address = ":".join([f"{random.randint(0, 255):02X}" for _ in range(6)])
        # Redirige vers la même page en ajoutant la MAC à l'URL.
        return redirect(f'/?mac={mac_address}')
    
    # Si la MAC est présente, rendre la page normalement.
    context = {
        'mac_address': mac_address,
    }
    
    return render(request, 'simulator/index.html', context)
