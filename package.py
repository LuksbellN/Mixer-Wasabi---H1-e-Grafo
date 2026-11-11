"""Cria um ZIP separado com o código, os dados e os resultados."""
import hashlib
import json
from pathlib import Path
import zipfile

from pypdf import PdfReader

from analyze import ROOT, save_json, utc


def main():
    archive = ROOT/'Wasabi_H1_Lucas_Belchior_codigo_dados.zip'
    files = sorted(set([*ROOT.glob('*.py'), ROOT/'README.md', ROOT/'requirements.txt',
                        *[p for p in (ROOT/'data').rglob('*') if p.is_file() and p.suffix != '.tmp'],
                        *[p for p in (ROOT/'results').rglob('*') if p.is_file()]]))
    inventory = []
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=7) as z:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            body = path.read_bytes()
            z.writestr('Wasabi_H1/' + relative, body)
            inventory.append({'path': relative, 'bytes': len(body),
                              'sha256': hashlib.sha256(body).hexdigest()})
        z.writestr('Wasabi_H1/INVENTORY.json', json.dumps(inventory, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP corrompido')
        for item in inventory:
            if hashlib.sha256(z.read('Wasabi_H1/' + item['path'])).hexdigest() != item['sha256']:
                raise ValueError('Conteúdo do ZIP divergente')
    pdf = ROOT/'report/Wasabi_H1_Lucas_Belchior.pdf'
    reader = PdfReader(pdf)
    if reader.attachments:
        raise ValueError('O PDF deve estar sem anexos; gere-o novamente com build_report.py')
    result = {'created_utc': utc(), 'files_in_zip': len(inventory), 'zip_bytes': archive.stat().st_size,
              'zip_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'pdf_pages': len(reader.pages), 'pdf_attachments': 0,
              'pdf_bytes': pdf.stat().st_size,
              'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest()}
    # Kept outside results to avoid recursively packaging a hash of the old package.
    save_json(ROOT/'report/package_verification.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
