# GoldBet Piedimonte — Gestionale a due casse

> **Versione per GitHub e hosting online inclusa:** segui prima [`GUIDA-ONLINE-GITHUB.md`](GUIDA-ONLINE-GITHUB.md). Le istruzioni sotto descrivono il funzionamento locale originario e non la pubblicazione su Internet.

**Versione:** 1.0 — applicazione web locale, pronta da avviare e configurare.

Il programma gestisce **Cassa 1** e **Cassa 2** con distinte indipendenti e un'**unica rubrica clienti**. Non contiene movimenti finti: all'inizio il database è vuoto.

## Avvio semplice su Windows

1. Installa **Python 3.11 o successivo** da https://www.python.org/downloads/ . Durante l'installazione seleziona **Add Python to PATH** (se presente).
2. Estrai completamente lo ZIP in una cartella stabile sul **PC principale** del negozio.
3. Apri la cartella ed esegui **`AVVIA-WINDOWS.bat`**. Lascia aperta la finestra nera: è il server che condivide i dati.
4. Apri **http://127.0.0.1:8787** sul PC principale.
5. Al primo avvio crea la password dell'**amministratore** (almeno 10 caratteri). Lo username iniziale sarà **`admin`**.
6. Accedi come amministratore, vai su **Impostazioni → Aggiungi operatore** e crea gli account degli addetti alle casse.
7. Prima di usare il programma con dati veri, prova le operazioni con nominativi di test e verifica i conteggi.

**Mac / Linux:** dalla cartella del progetto esegui `./AVVIA-MAC-LINUX.sh` oppure `python3 server.py` e apri http://127.0.0.1:8787 .

**Non è necessario installare pacchetti Python esterni**, né creare un account online: il programma usa Python, SQLite e un'interfaccia web locale.

## Usare due PC contemporaneamente

Il programma va avviato **una sola volta sul PC principale**, che conserverà il database. Gli altri PC devono essere sulla **stessa rete locale** e aprire il suo indirizzo (senza copiare e avviare un secondo server).

- Sul PC principale, apri il Prompt dei comandi e digita `ipconfig`.
- Cerca l'**indirizzo IPv4** della scheda di rete attiva (ad esempio `192.168.1.50`).
- Da ciascuna cassa, apri un browser e digita **`http://192.168.1.50:8787`**, sostituendo l'IP con quello reale.
- Se Windows Firewall chiede un'autorizzazione, consenti al processo Python l'accesso **solo su reti private**.
- È consigliato assegnare al PC principale un IP locale stabile dal router.

**Importante:** il PC principale deve restare **acceso** e il server **in esecuzione** per permettere l'accesso dalle casse. Il sito è utilizzabile anche su smartphone collegati alla stessa rete.

## Cosa contiene

### 1. Login e scelta cassa

Ogni operatore ha username e password. Nell'intestazione si sceglie **Cassa 1** o **Cassa 2**; ogni cassa può avere una sola distinta aperta. I movimenti sono attribuiti all'operatore che ha aperto la distinta; un altro operatore non può modificarla, salvo l'amministratore.

### 2. Apertura distinta

All'arrivo si apre il turno inserendo i **contanti fisici iniziali**. Data e operatore sono automatici.

### 3. Verde, rosso e blu

Dalla dashboard si trascrivono i due importi mostrati dal terminale GoldBet:

- **Verde:** bollette emesse.
- **Rosso:** vincite pagate.
- **Blu:** verde meno rosso, calcolato automaticamente.

**Non esiste ancora un'integrazione diretta con il software GoldBet:** i totali del terminale vanno inseriti manualmente. La rubrica e le distinte sono invece collegate direttamente tra loro.

### 4. Rubrica comune

Si aggiunge un cliente con **nome e cognome obbligatori**. Ogni cliente ha scheda, debito residuo e storico di entrambi i terminali. Si possono correggere nome e cognome mantenendo i movimenti. Il programma avvisa quando trova un omonimo, ma consente di registrarlo se davvero è un'altra persona.

### 5. Movimenti della distinta

- **Giocata a debito (−):** aumenta il debito del cliente ed è un'uscita nel calcolo della cassa.
- **Acconto / saldo (+):** diminuisce il debito del cliente ed è un'entrata nel calcolo della cassa.

Un movimento viene inserito **una volta sola**: appare sia nella distinta della specifica cassa sia nella scheda del cliente nella rubrica comune. Un pagamento maggiore del debito residuo viene rifiutato per evitare errori. Un movimento errato può essere **annullato con motivazione**, senza eliminare le informazioni storiche; le distinte già chiuse non sono modificabili.

### 6. Notifiche automatiche

- **Debito saldato:** avviso verde quando il debito scende a zero.
- **Mancato saldo dopo 7 giorni:** avviso rosso se resta insoluto un importo dalla prima giocata non ancora saldata.

I pagamenti vengono imputati alle **giocate più vecchie per prime**: se un acconto copre completamente la giocata più vecchia, la data della prima giocata ancora aperta si sposta in avanti. Il programma evita duplicati degli avvisi attivi e mostra le notifiche a entrambe le casse.

Il server verifica le scadenze periodicamente mentre è acceso. Il browser controlla i nuovi dati ogni circa 12 secondi. Le notifiche sono **interne all'app**, non SMS o notifiche push sul telefono.

### 7. Chiusura turno

Il sistema calcola:

`PC teorico = saldo blu + contanti iniziali + entrate clienti − uscite a debito`

L'operatore inserisce **contanti fisici contati** e il sistema mostra:

`Differenza finale = PC teorico − contanti fisici`

- **0,00 €:** quadratura corretta.
- **Differenza positiva:** ammanco di contanti fisici.
- **Differenza negativa:** eccedenza di contanti fisici.

Si possono annotare arrotondamenti, resti sbagliati e mance. Dopo la conferma, la distinta viene archiviata in modalità non modificabile.

### 8. Archivio e backup

L'archivio mostra **solo la cassa selezionata**, senza riepilogo misto delle casse. Le distinte possono essere aperte e stampate o salvate come PDF usando **Stampa → Salva come PDF** nel browser.

L'amministratore può scaricare un **backup SQLite completo** dalle Impostazioni. È consigliabile farlo ogni giorno e conservare una copia su un dispositivo esterno sicuro.

### 9. Aspetto e logo

L'interfaccia ha un tema scuro con accenti giallo oro, tre schede verde/rosso/blu e intestazione **GoldBet Piedimonte**. Il wordmark iniziale è una resa tipografica ispirata ai colori del marchio, **non una riproduzione certificata del logo ufficiale**. Se avete il file autorizzato del logo, caricatelo da **Impostazioni → Logo GoldBet Piedimonte** (PNG/JPG/WebP, max 1,5 MB): apparirà su tutte le postazioni.

## Dove sono memorizzati i dati?

Nella cartella `data/`, nel file **`gestionale.sqlite3`** creato automaticamente al primo avvio.

Questo file è il database del negozio: contiene clienti, saldi, movimenti, distinte, account, password protette da hash e notifiche. **Non eliminarlo né sostituirlo durante gli aggiornamenti**. I file temporanei `-wal` e `-shm` sono normali durante l'uso; per un backup affidabile utilizza il pulsante **Scarica backup**.

## Sicurezza e verifiche prima dell'uso reale

- Utilizzare su **rete privata e affidabile**, non esporre direttamente la porta 8787 su Internet. Per accesso da remoto occorre far predisporre a un tecnico una soluzione con **HTTPS e autenticazione adeguata**, preferibilmente dietro VPN.
- Conservare i backup protetti e controllare chi può accedere a nominativi, debiti e credenziali. Predisporre le informazioni e misure privacy richieste dal GDPR con il titolare dell'attività.
- Questo è un **gestionale interno di registrazioni contabili**. Non emette scommesse, non incassa pagamenti online, non sostituisce il sistema autorizzato del concessionario e non invia dati all'ADM.
- **Verificare con il concessionario e con un professionista competente** la liceità delle prassi di gioco con pagamento differito e le corrette procedure contabili prima di usare il sistema con operazioni reali. Lo sviluppo del registro non certifica né autorizza tali prassi.
- Prima di un impiego continuativo, fare una prova operativa e una valutazione di sicurezza con un tecnico, compresi backup, ripristino e politiche di accesso.

## Diagnostica

**Il browser non apre il programma**: controlla che `AVVIA-WINDOWS.bat` sia ancora aperto e che Python sia installato; prova http://127.0.0.1:8787 sul server.

**Il secondo PC non si collega**: verifica stesso Wi‑Fi/LAN, IP reale del server, firewall privato, servizio acceso.

**Due distinte sulla stessa cassa**: il sistema blocca per sicurezza una seconda apertura finché la prima è aperta. Chiudi il turno in corso oppure accedi come amministratore se serve risolvere un problema.

**La rubrica non si aggiorna**: verifica la connessione al server e usa Aggiorna. Le postazioni non devono utilizzare due copie diverse del database.

**Problemi di data/ora**: sistema correttamente l'orologio del PC principale; le scadenze dei 7 giorni utilizzano l'ora italiana.

## File del progetto

- `server.py`: server HTTP, autenticazione, database, API, calcoli e notifiche.
- `static/index.html`, `styles.css`, `app.js`: interfaccia utente.
- `AVVIA-WINDOWS.bat`, `AVVIA-MAC-LINUX.sh`: avvio.
- `tests/test_workflow.py`: test automatici di due casse, saldi, scadenze e chiusura.

### Test automatici

Dalla cartella del progetto, esegui:

`python -m unittest discover -s tests -v`

La suite usa un database **temporaneo separato** e non modifica i dati reali del negozio.