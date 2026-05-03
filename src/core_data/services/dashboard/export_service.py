"""
Services d'exportation des clients (CSV + PDF).
Colonnes : payload (tous les champs) + devices + tags + notes + métadonnées.
"""
import csv
import io
from datetime import datetime
from django.http import HttpResponse
from django.utils import timezone

from core_data.models import OwnerClient


def _get_all_payload_keys(queryset):
    """Collecte l'union de toutes les clés payload sur le queryset."""
    keys = []
    seen = set()
    for client in queryset:
        for k in (client.payload or {}).keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


def _format_devices(client):
    """Formate les appareils d'un client en texte lisible."""
    devices = client.devices.all()
    if not devices:
        return ''
    parts = []
    for d in devices:
        ua = f' ({d.user_agent[:60]}…)' if d.user_agent else ''
        parts.append(f'{d.mac_address}{ua}')
    return ' | '.join(parts)


def _last_seen(client):
    """
    Retourne la date de dernière activité connue :
    - client.last_seen si renseigné (mis à jour par le hotspot)
    - sinon le max des ClientDevice.last_seen (auto_now=True)
    - sinon None
    """
    if client.last_seen:
        return client.last_seen
    latest = client.devices.order_by('-last_seen').first()
    return latest.last_seen if latest else None


def export_csv(queryset) -> HttpResponse:
    """
    Génère un fichier CSV complet pour le queryset donné.
    Colonnes : payload (toutes clés) | MAC principale | Appareils | Email | Téléphone |
               Prénom | Nom | Vérifié | Tags | Notes | Créé le | Vu dernièrement
    """
    queryset = queryset.prefetch_related('devices')
    payload_keys = _get_all_payload_keys(queryset)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"clients_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    headers = list(payload_keys) + [
        'MAC', 'Appareils', 'Vérifié', 'Tags', 'Notes',
        'Créé le', 'Vu dernièrement',
    ]
    writer.writerow(headers)

    for client in queryset:
        payload = client.payload or {}
        row = [payload.get(k, '') for k in payload_keys]
        row += [
            client.mac_address,
            _format_devices(client),
            'Oui' if client.is_verified else 'Non',
            ', '.join(client.tags or []),
            client.notes or '',
            client.created_at.strftime('%d/%m/%Y %H:%M') if client.created_at else '',
            _last_seen(client).strftime('%d/%m/%Y %H:%M') if _last_seen(client) else '',
        ]
        writer.writerow(row)

    return response


def export_pdf(queryset) -> HttpResponse:
    """
    Génère un fichier PDF (tableau) pour le queryset donné via ReportLab.
    Colonnes allégées pour la lisibilité : Nom/Prénom | Contact | MAC | Appareils |
    Vérifié | Tags | Créé le
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT

    queryset = queryset.prefetch_related('devices')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=7, leading=9)
    title_style = ParagraphStyle('title', parent=styles['Heading1'], fontSize=13, spaceAfter=6)

    elements = []
    elements.append(Paragraph('Export Clients', title_style))
    elements.append(Paragraph(
        f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} — {queryset.count()} client(s)",
        styles['Normal']
    ))
    elements.append(Spacer(1, 8 * mm))

    col_headers = ['Prénom', 'Nom', 'Email', 'Téléphone', 'MAC principale',
                   'Appareils', 'Vérifié', 'Tags', 'Notes', 'Créé le', 'Vu le']

    data = [col_headers]

    for client in queryset:
        devices_text = _format_devices(client)
        data.append([
            Paragraph(client.first_name or '—', small),
            Paragraph(client.last_name or '—', small),
            Paragraph(client.email or '—', small),
            Paragraph(client.phone or '—', small),
            Paragraph(client.mac_address or '—', small),
            Paragraph(devices_text or '—', small),
            'Oui' if client.is_verified else 'Non',
            Paragraph(', '.join(client.tags or []) or '—', small),
            Paragraph((client.notes or '—')[:80], small),
            client.created_at.strftime('%d/%m/%Y') if client.created_at else '—',
            _last_seen(client).strftime('%d/%m/%Y') if _last_seen(client) else '—',
        ])

    col_widths = [28*mm, 28*mm, 40*mm, 30*mm, 35*mm, 55*mm, 16*mm, 30*mm, 35*mm, 22*mm, 22*mm]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4ff')]),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d1d5db')),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    filename = f"clients_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
