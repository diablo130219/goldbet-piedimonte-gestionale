# Pubblicazione GoldBet Piedimonte su Render Free + Neon Free

Stato: progetto convertito per PostgreSQL (Neon) e hosting gratuito Render.

## Configurazione

1. Progetto Neon dedicato `goldbet-piedimonte-gestionale`, regione EU Francoforte.
2. Servizio Render **Free** (Python, regione Frankfurt), GitHub `diablo130219/goldbet-piedimonte-gestionale`, branch `main`.
3. Build: `pip install -r requirements.txt && python -m compileall -q server.py storage.py`.
4. Start: `python server.py`. Health check: `/healthz`.
5. Segreti Render: `DATABASE_URL` (stringa SSL di Neon) e `GB_SETUP_TOKEN` (stringa casuale di almeno 24 caratteri). Ambiente `GB_PUBLIC=1`, `GB_SECURE_COOKIE=1`.
6. Non configurare dischi e non selezionare piani a pagamento. Il server Cloud rifiuta l'avvio quando manca il database PostgreSQL.
7. Aprire l'URL `onrender.com`, inserire il token di configurazione una sola volta, creare l'amministratore e gli operatori.
8. Fare una simulazione nelle due casse: apertura, registrazione cliente, debito, acconto, saldo, notifiche, quadratura e archivio. Verificare da due browser differenti.

## Limiti gratuiti

- Render può andare in sospensione dopo inattività, con ritardo al primo accesso. Le risorse gratuite del workspace sono condivise con altri servizi.
- Neon ha limiti su consumo, storage e connessioni; la sospensione del servizio può ritardare notifiche scadute fino al risveglio o al prossimo accesso.
- La pagina interroga il server ogni ~3 secondi **mentre è aperta**: non è una connessione push continua.
- Il DB Neon conserva i dati dopo i deploy di Render, ma non sostituisce un backup indipendente.
- Backup amministratore PostgreSQL: esportazione `.json` sensibile; conservare fuori da GitHub. L'importazione automatica non è prevista.

## Per l'utilizzo reale

Prima dell'impiego con clienti reali servono controlli di sicurezza, privacy/GDPR, verifica delle procedure con il concessionario e un piano di backup/ripristino. Non inviare dati personali nel repository. Evitare di mettere in produzione questa versione gratuita come unica fonte contabile senza collaudo e sistema di continuità.