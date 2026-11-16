# GoldBet Piedimonte — Gestionale Online

Gestionale interno per due casse con rubrica condivisa e quadratura dei turni. L’accesso ai dati richiede login. **Non è una piattaforma pubblica di scommesse**.

## Deploy gratuito (fase di test)

- **GitHub:** codice e aggiornamenti, senza password o dati clienti.
- **Render Free:** server Python. Può sospendersi dopo inattività; nessuna garanzia di continuità.
- **Neon Free:** PostgreSQL persistente. Clienti, turni, saldi, notifiche, utenti e logo vengono salvati su Neon.
- **HTTPS:** attivo tramite il dominio Render `onrender.com`.

Il file `render.yaml` specifica `plan: free`, senza disco Render. `DATABASE_URL` e `GB_SETUP_TOKEN` sono **segreti da configurare su Render**, mai in GitHub. Il server cloud rifiuta l'avvio se non è configurato PostgreSQL (per evitare perdita dati sul filesystem temporaneo).

Per iniziare aprire il sito Render, inserire il token di configurazione e creare l'account admin. Nessuna credenziale admin è presente nel codice.

### Sviluppo/test locale

```bash
python -m unittest discover -s tests -v
python server.py
```

Per testare con Neon anziché SQLite, installare `pip install -r requirements.txt` e impostare `DATABASE_URL` nell'ambiente, mai in file versionati.

### Backup e logo

Da Impostazioni → Scarica backup, SQLite esporta `.sqlite3`; Neon esporta `.json` sensibile (tabelle e password hash). Conservare **offline e cifrato**; verificare un ripristino con procedura documentata prima dell'uso reale. Il logo caricato viene conservato su Neon.

### Avvertenze

Uso pilota con dati fittizi. Prima di usare nomi e operazioni reali: audit di sicurezza, informativa GDPR, autorizzazioni del concessionario e backup/test di ripristino. Il piano gratuito non è indicato per operatività che richiede continuità garantita.