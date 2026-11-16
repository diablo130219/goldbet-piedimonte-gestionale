# GoldBet Piedimonte — versione predisposta per GitHub + Render

## Cosa cambia rispetto alla versione locale

Il codice rimane su GitHub, preferibilmente in un **repository privato**. Render ospita il sito web HTTPS, mentre un disco persistente conserva il database SQLite e il logo caricabile. I computer delle due casse e il telefono accedono allo **stesso sito** con utenti e password distinti. La rubrica e le distinte sono condivise. La pagina controlla i cambiamenti ogni **3 secondi** mentre è aperta (quasi in tempo reale, non push istantaneo).

> Nessun servizio viene pubblicato automaticamente dallo ZIP. Per avere un URL reale occorre collegare l'account GitHub a Render, autorizzare la creazione del servizio e configurare il piano. Può comportare costi: **non scegliere il piano gratuito** con SQLite perché il disco locale viene cancellato a ogni riavvio/deploy. Il file `render.yaml` usa `plan: starter` e un disco da 1 GB.

## Guida pratica

1. Su GitHub, crea un **repository privato**, per esempio `goldbet-piedimonte-gestionale`, e carica tutti i file presenti nella cartella del progetto, compreso `render.yaml` e `.gitignore`, senza caricare un eventuale file `data/gestionale.sqlite3`.
2. Apri **https://dashboard.render.com** e collega GitHub. Crea una nuova **Blueprint** dal repository. Controlla che il servizio sia un `web service` Python con `plan: starter`, `disk` su `/var/data`, dimensione 1 GB e avvio `python server.py`.
3. Render chiederà il valore della variabile segreta `GB_SETUP_TOKEN`: genera un codice casuale di almeno 24 caratteri (meglio almeno 32; non inserirlo nel repository). Conserva questo codice in un gestore di password. Render assegnerà un indirizzo HTTPS `*.onrender.com` al servizio.
4. Apri il sito HTTPS ottenuto, inserisci nome amministratore, password forte e codice segreto di attivazione. Crea gli operatori e prova Cassa 1 e Cassa 2 da browser distinti.
5. Verifica l'aggiornamento dei saldi tra le casse (entro pochi secondi), la quadratura e gli avvisi prima di registrare dati reali.
6. Gli aggiornamenti al codice caricati su GitHub possono essere ridistribuiti da Render. Il database e il logo restano nel disco persistente (salvo rimozione volontaria del disco/servizio).

## Sicurezza indispensabile

- Questo è un progetto adattato per la **prima distribuzione tecnica**, non un servizio già pubblicato, collaudato e certificato per dati personali reali. Prima dell'uso operativo fare revisione di sicurezza, controlli accessi, verifica privacy/GDPR, verifica con il concessionario e test di ripristino dei backup.
- Non pubblicare mai nomi, debiti, backup o password nel repository GitHub. L'accesso al sito deve essere riservato agli operatori autorizzati; non rendere i dati pubblici.
- Le password degli utenti e il codice di attivazione sono cose diverse. Dopo il primo setup il codice resta nella configurazione privata di Render, non visibile agli utenti normali.
- Il download dei backup SQLite è previsto nell'area riservata all'amministratore: esegui backup regolari **al di fuori di Render**, criptati e con un ripristino testato. Un disco persistente non sostituisce il backup.
- Un singolo disco SQLite è adatto a un singolo server piccolo, non a più istanze parallele. Per crescita, conviene migrare a PostgreSQL e aggiungere audit e controlli di sicurezza avanzati.
- Ogni aggiornamento del server durante il deploy può causare una breve interruzione; il requisito “sempre online” non è una garanzia di disponibilità assoluta.
- Il logo iniziale è un marchio testuale, non una versione certificata del logo ufficiale: caricare solo un logo del quale si hanno diritti d’uso.

## Sviluppo locale

Avvia con `python server.py`, visita `http://127.0.0.1:8787`. Senza `GB_SETUP_TOKEN` la prima configurazione è consentita solo in locale. I test si eseguono con `python -m unittest discover -s tests -v`.