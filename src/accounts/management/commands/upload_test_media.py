'''
Management command: python manage.py upload_test_media

Effectue un test complet du bucket de stockage (S3-compatible) :
  1. WRITE   — Upload d'un fichier texte
  2. EXISTS  — Vérification que le fichier existe
  3. READ    — Lecture et vérification du contenu
  4. URL     — Génération d'une URL présignée et téléchargement HTTP réel
  5. UPLOAD  — Upload d'une vraie image PNG (générée en mémoire)
  6. DELETE  — Suppression de tous les fichiers de test
  7. VERIFY  — Vérification que les fichiers ont bien été supprimés

Usage:
  python manage.py upload_test_media            # Exécution normale
  python manage.py upload_test_media --keep     # Garde les fichiers après le test
'''

import io
import time
import struct
import zlib
import urllib.request

from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _make_png(width: int = 64, height: int = 64) -> bytes:
    """
    Génère un fichier PNG minimal valide en pur Python (sans Pillow).
    Produit un carré divisé en 4 quadrants colorés.
    """
    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    # En-tête PNG
    header = b"\x89PNG\r\n\x1a\n"

    # Chunk IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    # Chunk IDAT : pixels RGB
    raw_rows = []
    for y in range(height):
        row = [0]  # filtre "None" pour chaque ligne
        for x in range(width):
            if x < width // 2 and y < height // 2:
                row += [220, 80, 80]      # rouge (haut-gauche)
            elif x >= width // 2 and y < height // 2:
                row += [80, 160, 220]     # bleu (haut-droit)
            elif x < width // 2 and y >= height // 2:
                row += [80, 200, 120]     # vert (bas-gauche)
            else:
                row += [240, 190, 60]     # jaune (bas-droit)
        raw_rows.append(bytes(row))

    raw = b"".join(raw_rows)
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")

    return header + ihdr + idat + iend


SEPARATOR = "─" * 58


class Command(BaseCommand):
    help = "Test complet du bucket : write, exists, read, URL, image, delete, verify."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Conserve les fichiers de test dans le bucket après l'exécution.",
        )

    # ── entrée principale ────────────────────────────────────
    def handle(self, *args, **options):
        self.keep = options["keep"]
        self.uploaded: list[str] = []
        self.errors: int = 0

        self._header()

        self._test_write_text()
        self._test_exists()
        self._test_read()
        self._test_presigned_url()
        self._test_write_image()

        if not self.keep:
            self._test_delete()
            self._test_verify_deleted()
        else:
            self._warn("--keep activé : fichiers conservés dans le bucket.")

        self._footer()

    # ── étapes de test ──────────────────────────────────────

    def _test_write_text(self):
        self._step("1/6", "WRITE", "Upload d'un fichier texte")
        path = "__bucket_test__/hello.txt"
        content = b"Bucket OK - " + str(time.time()).encode()
        try:
            saved = default_storage.save(path, ContentFile(content))
            self.uploaded.append(saved)
            self._ok(f"Fichier sauvegardé : {saved}")
        except Exception as e:
            self._fail(f"Impossible d'écrire : {e}")

    def _test_exists(self):
        self._step("2/6", "EXISTS", "Vérification de l'existence du fichier")
        if not self.uploaded:
            self._skip("Aucun fichier uploadé à l'étape précédente.")
            return
        path = self.uploaded[0]
        try:
            exists = default_storage.exists(path)
            if exists:
                self._ok(f"default_storage.exists({path!r}) → True")
            else:
                self._fail(f"Le fichier {path!r} est introuvable dans le bucket !")
        except Exception as e:
            self._fail(f"Erreur lors de exists() : {e}")

    def _test_read(self):
        self._step("3/6", "READ", "Lecture et vérification du contenu")
        if not self.uploaded:
            self._skip("Aucun fichier à lire.")
            return
        path = self.uploaded[0]
        try:
            with default_storage.open(path, "rb") as f:
                data = f.read()
            if data.startswith(b"Bucket OK"):
                self._ok(f"Contenu lu avec succès ({len(data)} octets) : {data[:30]!r}…")
            else:
                self._fail(f"Contenu inattendu : {data[:60]!r}")
        except Exception as e:
            self._fail(f"Erreur lors de open() : {e}")

    def _test_presigned_url(self):
        self._step("4/6", "URL", "Génération URL + téléchargement HTTP réel")
        if not self.uploaded:
            self._skip("Aucun fichier pour générer une URL.")
            return
        path = self.uploaded[0]
        try:
            url = default_storage.url(path)
            self._ok(f"URL générée :\n    {url}")

            # Téléchargement HTTP réel
            req = urllib.request.Request(url, headers={"User-Agent": "django-bucket-test/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                body = resp.read()

            if status == 200 and body.startswith(b"Bucket OK"):
                self._ok(f"HTTP {status} — fichier téléchargé ({len(body)} octets). ✓")
            else:
                self._fail(f"HTTP {status} — contenu inattendu : {body[:60]!r}")
        except Exception as e:
            self._fail(f"Erreur URL/téléchargement : {e}")

    def _test_write_image(self):
        self._step("5/6", "IMAGE", "Upload d'une vraie image PNG (64×64 px)")
        path = "__bucket_test__/test_image.png"
        png_bytes = _make_png(64, 64)
        try:
            saved = default_storage.save(path, ContentFile(png_bytes, name="test_image.png"))
            self.uploaded.append(saved)
            url = default_storage.url(saved)
            self._ok(
                f"Image PNG ({len(png_bytes)} octets) uploadée : {saved}\n"
                f"    URL : {url}"
            )
        except Exception as e:
            self._fail(f"Impossible d'uploader l'image : {e}")

    def _test_delete(self):
        self._step("6/6", "DELETE", f"Suppression de {len(self.uploaded)} fichier(s)")
        for path in self.uploaded:
            try:
                default_storage.delete(path)
                self._ok(f"Supprimé : {path}")
            except Exception as e:
                self._fail(f"Impossible de supprimer {path!r} : {e}")

    def _test_verify_deleted(self):
        self._step("✓", "VERIFY", "Vérification post-suppression")
        all_gone = True
        for path in self.uploaded:
            try:
                still_there = default_storage.exists(path)
                if still_there:
                    self._fail(f"Toujours présent après suppression : {path!r}")
                    all_gone = False
                else:
                    self._ok(f"Confirmé absent : {path}")
            except Exception as e:
                self._fail(f"Erreur lors de la vérification de {path!r} : {e}")
        if all_gone and self.uploaded:
            self._ok("Tous les fichiers de test ont été supprimés avec succès.")

    # ── affichage ───────────────────────────────────────────

    def _header(self):
        self.stdout.write(f"\n{SEPARATOR}")
        self.stdout.write(self.style.HTTP_INFO("  🪣  TEST COMPLET DU BUCKET DE STOCKAGE"))
        self.stdout.write(f"{SEPARATOR}\n")

    def _footer(self):
        self.stdout.write(f"\n{SEPARATOR}")
        if self.errors == 0:
            self.stdout.write(self.style.SUCCESS("  ✅  Tous les tests ont réussi ! Bucket 100% fonctionnel."))
        else:
            self.stdout.write(
                self.style.ERROR(f"  ❌  {self.errors} erreur(s) détectée(s). Vérifiez les logs ci-dessus.")
            )
        self.stdout.write(f"{SEPARATOR}\n")

    def _step(self, num, label, desc):
        self.stdout.write(f"\n[{num}] {self.style.WARNING(label):<20} {desc}")
        self.stdout.write(f"{' ':>5}{ '-' * 50}")

    def _ok(self, msg):
        for line in msg.splitlines():
            self.stdout.write(f"{' ':>5}" + self.style.SUCCESS(f"✓  {line}"))

    def _fail(self, msg):
        self.errors += 1
        for line in msg.splitlines():
            self.stdout.write(f"{' ':>5}" + self.style.ERROR(f"✗  {line}"))

    def _warn(self, msg):
        self.stdout.write(f"{' ':>5}" + self.style.WARNING(f"⚠  {msg}"))

    def _skip(self, msg):
        self.stdout.write(f"{' ':>5}⊘  {msg}")
