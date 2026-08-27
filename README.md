# Aurora

Gestione progetti e documentazione tecnica. Gira in rete locale, senza cloud.

## Installazione

Dalla sessione 12 la strada normale e' la **configurazione guidata**: si
prepara il database, si avvia il server e si apre il browser. Il resto lo
spiega Aurora, un passo per volta, senza aprire nessun file di testo.

1. Preparare PostgreSQL seguendo `scripts/setup_postgres.md` (parte B).
2. Copiare `.env.example` in `.env` e adattare `DATABASE_URL`.
3. Creare l'ambiente virtuale: `python -m venv .venv`
4. Attivarlo: `.venv\Scripts\activate`
5. Installare le dipendenze: `pip install -r requirements.txt`
6. Applicare le migrazioni: `alembic upgrade head`
7. Avviare il server: `uvicorn app.main:app --reload`
8. Aprire <http://localhost:8000/>. Su un database vuoto Aurora manda da sola
   alla **configurazione guidata**: sei passi - il database, la prima persona,
   l'archivio dei file, le classificazioni, il percorso delle fasi, la posta -
   ciascuno con la sua spiegazione e un pulsante che verifica. Si puo'
   interrompere e riprendere: Aurora si ricorda a che punto era.
9. Rendere il registro delle operazioni a sola aggiunta, seguendo
   `scripts/hardening_db.md`. **Va fatto dopo il punto 6 e non prima**: la
   migrazione riempie le colonne delle righe gia' scritte, ed e' l'ultimo
   `UPDATE` che verra' mai eseguito su quella tabella.
10. Programmare la copia di sicurezza notturna, seguendo
    `docs/BACKUP_E_RIPRISTINO.md` (sezione 5). Finche' non e' fatta, la pagina
    di diagnostica lo segnala in rosso.
11. Controllare che vada tutto bene: <http://localhost:8000/diagnostica>
12. Eseguire i test: `pytest`
13. In caso di problemi, leggere il registro: `Get-Content logs\aurora.log -Tail 50`

**Dalla riga di comando, per chi preferisce.** I dati iniziali si creano anche
con `python scripts/seed.py`, che crea l'utente `admin` e stampa **una volta
sola** la sua password. I due percorsi leggono lo stesso file
(`config/dati_iniziali.toml`) e danno lo stesso sistema.

## Dove finiscono i file caricati

In `STORAGE_PATH` (di partenza `storage/`), depositati con il nome della loro
impronta SHA-256 e non con il loro:

```
storage/objects/3f/9a/3f9a2c11...   il file
storage/tmp/                        i file a meta' scrittura
storage/posta/                      la cartella della posta (MAIL_LOCAL_PATH)
storage/posta_graph.json            dove Aurora era arrivata a leggere la casella
```

Il nome originale, il tipo e tutti i metadati stanno nel database. Due
caricamenti dello stesso identico file occupano un file solo. La cartella
`tmp/` in condizioni normali e' vuota: quello che ci resta e' un caricamento
interrotto, e non lo riferisce nessuna riga del database.

**`STORAGE_PATH` va nei backup del server**: il database senza quella cartella
e' un elenco di documenti che non si aprono. In produzione conviene un disco
dedicato.

## Chi vede che cosa

Un utente accede a un documento se e' il **creatore**, se e' il **project
manager** del progetto a cui il documento appartiene, oppure se e' **assegnato**
a quel progetto e la matrice dei permessi consente al suo ruolo quell'operazione
su quella classificazione.

La matrice si corregge da <http://localhost:8000/permessi> (serve il ruolo di
creatore): una riga per ruolo di progetto, tre spunte per classificazione. Il
salvataggio passa da una conferma che elenca che cosa cambia, e ogni casella
corretta finisce nel registro delle operazioni con il valore precedente e
quello successivo. **Ha effetto subito**, anche su chi e' collegato in quel
momento: nessuno deve uscire e rientrare.

Per sapere che cosa vede una persona senza entrare con le sue credenziali:
dall'elenco degli utenti, il pulsante **Verifica accessi**.

Nel codice la regola sta in un punto solo, `app/services/permissions.py`, e ci
si arriva sempre con `permissions.puo(db, utente, azione, oggetto)`. Non ci sono
controlli di permesso da nessun'altra parte, nemmeno nei template: c'e' un test
che lo verifica leggendo i sorgenti.

## Il registro delle operazioni

Ogni operazione che cambia qualcosa in Aurora lascia una riga in `audit_logs`:
chi, che cosa, su quale oggetto, quando, da quale indirizzo, con il valore di
prima e quello di dopo e una frase in italiano che si capisce senza conoscere
il programma.

Si consulta da <http://localhost:8000/registro> (serve il ruolo di creatore),
con i filtri per intervallo di date, utente, tipo di azione e tipo di oggetto,
e la ricerca sulla descrizione. Da li' si esporta in CSV quello che si sta
guardando - e l'esportazione stessa finisce nel registro.

La storia di un oggetto singolo si guarda invece dalla sua scheda, linguetta
**Storico**: prodotti, versioni, progetti, documenti, messaggi di posta e
persone ce l'hanno tutti, e la vede chi vede l'oggetto.

**Le righe si aggiungono e non si tolgono.** Non e' una promessa del programma:
l'utente PostgreSQL con cui Aurora si collega ha su quella tabella `SELECT` e
`INSERT` e nient'altro. Si verifica cosi':

```powershell
psql -U aurora_app -h localhost -d aurora -c "UPDATE audit_logs SET description = 'x' WHERE seq = 1;"
```

La risposta attesa e' `permesso negato per la tabella audit_logs`. Se invece
risponde `UPDATE 1`, l'irrobustimento non e' stato applicato: vedi
`scripts/hardening_db.md`.

In piu', ogni voce porta l'impronta della precedente, cosi' una manomissione
fatta scavalcando il programma - da chi amministra il database - resta
comunque visibile:

```powershell
python scripts/verifica_audit.py
```

Le voci **non si cancellano mai**, nemmeno le piu' vecchie. Per consegnarne una
copia a chi verifica, o per tenerne una fuori dal database, c'e'
`python scripts/archivia_audit.py --anni 5`, che scrive un file compresso e non
tocca il database.

## La posta

Aurora archivia i messaggi di posta e li attacca alla **versione di prodotto**
di cui parlano. Il file `.eml` originale si conserva intero nell'archivio, come
ogni altro file, e resta sempre scaricabile.

**Da dove arrivano.** Lo dice `MAIL_PROVIDER` nel file `.env`. Con `locale`,
che e' quello che si usa oggi, Aurora legge i file `.eml` che trova in
`MAIL_LOCAL_PATH` e, dopo averli archiviati, li sposta:

```
storage/posta/               i messaggi ancora da leggere
storage/posta/elaborate/     quelli archiviati e attribuiti
storage/posta/quarantena/    quelli che aspettano una persona
```

Con `graph`, Aurora si collega alla **casella aziendale** di Microsoft 365,
legge i messaggi non letti della posta in arrivo e, dopo averli archiviati, li
sposta in due cartelle della casella stessa:

```
Posta in arrivo    i messaggi ancora da leggere
Elaborate          quelli archiviati e attribuiti
Quarantena         quelli che aspettano una persona
```

Le due cartelle le crea Aurora la prima volta che servono. **Dalla casella non
si cancella mai niente.**

**Come si configura la casella.** Tutto da
<http://localhost:8000/posta/configurazione> (serve il ruolo di creatore),
senza toccare nessun file di testo: ogni campo ha accanto un pulsante
**Verifica** che prova il collegamento e dice subito che cosa non torna. I
parametri li fornisce l'ufficio informatico: il documento gia' pronto da
mandargli - con i comandi PowerShell e la spiegazione del perche' - e'
`docs/RICHIESTA_IT.md`.

Serve la libreria `msal`, che si installa con `pip install -r requirements.txt`
insieme a tutto il resto. Se manca, la pagina di configurazione lo dice invece
di rompersi.

**Ogni quanto si controlla.** Con `MAIL_PROVIDER=graph` Aurora guarda la
casella ogni `MAIL_POLL_MINUTES` minuti (cinque, di partenza). Due controlli
non si sovrappongono mai, e il pulsante **Controlla adesso** nella pagina della
posta ne fa partire uno subito. Con `MAIL_PROVIDER=locale` l'orologio non parte:
i file `.eml` li mette una persona, che puo' premere il pulsante subito dopo.

**Quando scade il segreto dell'applicazione** la posta smette di arrivare, e
Microsoft non avvisa nessuno. Per questo la data di scadenza e' un parametro
(`MAIL_SECRET_EXPIRES_ON`): Aurora la segnala nella pagina di configurazione a
partire da trenta giorni prima, e sempre piu' forte man mano che si avvicina.

**Come si prova, senza toccare nessuna casella:**

```powershell
python scripts/genera_email_prova.py
```

Scrive ventiquattro messaggi che esercitano tutti i casi - oggetti corretti,
con `R:` e `Fwd:` davanti, senza codice, risposte in conversazione, allegati
grandi e accentati, un file malformato - usando i codici dei prodotti veri del
database. Poi si apre <http://localhost:8000/posta> e si preme **Controlla
adesso**. Rieseguendo tutto una seconda volta non compare nessun doppione.

**Come Aurora capisce a chi appartiene un messaggio**, nell'ordine:

1. l'oggetto scritto secondo la convenzione `[CODICE][Vn][MOTIVO]`,
   riconosciuto anche dietro a `R:`, `Re:`, `Fwd:`, `I:` accumulati;
2. il codice prodotto scritto in mezzo alla frase, senza parentesi;
3. il filo di conversazione: se un altro messaggio dello stesso scambio e' gia'
   archiviato e attribuito, si eredita la sua attribuzione;
4. la **quarantena**, che non e' un errore ma una domanda a una persona.

Il messaggio viene archiviato **sempre**, anche quando il file e' rovinato o
l'oggetto non dice niente: in quarantena, con scritto perche' e' li'.

**La quarantena** sta in <http://localhost:8000/posta/quarantena> (serve il
ruolo di creatore, perche' un messaggio non attribuito non appartiene a nessun
progetto e non c'e' nessuna matrice da consultare). Assegnando un messaggio,
Aurora propone di assegnare allo stesso prodotto anche gli altri messaggi della
stessa conversazione.

**Le sigle dei motivi** - `SPECS`, `RFQ`, `QUOTE`... - si cambiano da
<http://localhost:8000/posta/motivi>. Non governano lo smistamento: un
messaggio con un motivo fuori elenco viene attribuito lo stesso.

**Chi vede la posta** e' deciso dalla stessa matrice dei documenti: un
messaggio e' trattato come un documento di classificazione **Corrispondenza**
nel progetto della versione a cui e' attaccato.

## Come sta il sistema

<http://localhost:8000/diagnostica> (serve il ruolo di creatore) risponde alla
domanda «funziona tutto?» con dieci righe a semaforo. Ogni riga che non e'
verde **dice che cosa fare** - non che cosa e' successo: che cosa fare, con i
nomi veri delle cose.

| Riga | Che cosa guarda |
|---|---|
| database | risponde? in quanti millisecondi? |
| posta | da dove arriva, ultimo controllo riuscito, messaggi in 24 ore |
| quarantena | quanti messaggi aspettano una persona |
| copia di sicurezza | quando, com'e' andata, quanto ha copiato |
| disco | usato, libero, e **fra quanti mesi finisce** al ritmo attuale |
| archivio | file sul disco non riferiti, e file attesi che non ci sono |
| registro | quante voci, a quando risale l'ultima |
| contenuto | documenti, versioni, messaggi, persone attive |
| segreto della posta | fra quanti giorni scade |
| errori | quante righe di errore nelle ultime 24 ore |

Gli stessi dati in forma leggibile da un programma di sorveglianza stanno in
<http://localhost:8000/salute>, che risponde anche a chi non e' entrato e anche
quando il database e' spento. Il verdetto complessivo e' il campo `semaforo`
("verde", "giallo", "rosso"); `stato` continua a dire soltanto se il database
risponde, come faceva prima. Se Aurora e' raggiungibile da fuori la rete
dell'ufficio tecnico, la rotta si chiude scrivendo `HEALTH_TOKEN` nel `.env`.

**Quando PostgreSQL e' spento** Aurora non mostra un errore tecnico: mostra una
pagina che dice che il database non risponde e come riavviarlo, con la stessa
identica frase che comparirebbe nella diagnostica.

## Copie di sicurezza

I dati di Aurora stanno in **due posti** e vanno copiati tutti e due: il
database (chi ha caricato che cosa) e l'archivio dei file (il contenuto vero).

```powershell
python scripts\backup.py              una copia adesso
python scripts\ripristino.py --elenca le copie disponibili
python scripts\ripristino.py          ripristina l'ultima
```

L'archivio si copia **in modo incrementale** e la copia non si cancella mai;
i salvataggi del database ruotano, e se ne tengono `BACKUP_KEEP`. Il
salvataggio viene riletto prima di essere dichiarato buono: un file troncato
esiste e non e' vuoto, e ci si accorgerebbe che non vale il giorno in cui serve.

La procedura completa - la programmazione notturna con l'Utilita' di
pianificazione di Windows, il ripristino, e **come si prova il ripristino su
una macchina diversa prima della messa in esercizio** - e' in
`docs/BACKUP_E_RIPRISTINO.md`.

> Una copia di sicurezza che non e' mai stata ripristinata non e' una copia di
> sicurezza: e' una speranza.

## La guida in linea

<http://localhost:8000/aiuto> (basta essere entrati): otto pagine con indice e
ricerca - primi passi, come si carica un documento, versioni e stati, come si
fa avanzare un progetto, come si scrive l'oggetto delle email, la quarantena,
chi vede che cosa, glossario.

Sono file Markdown in `docs/guida/`: li corregge chiunque con un editore di
testo, la modifica si vede ricaricando la pagina, e si leggono anche senza
aprire Aurora - il che conta il giorno in cui Aurora non si apre.

Accanto ai campi non ovvi c'e' un **punto interrogativo** che porta alla
sezione della guida che li spiega.

## Se nessuno riesce piu' a entrare

Le password non si recuperano: nel database c'e' solo l'impronta argon2. Se ne
assegna una nuova dalla riga di comando, sul server:

```powershell
python scripts/reimposta_password.py admin
```

Stampa una password nuova, obbliga a cambiarla al primo accesso e chiude tutte
le sessioni aperte di quell'utente. Funziona con qualunque nome utente, non
solo `admin`, e sa riattivare un utente disattivato.

## Da leggere prima di modificare il codice

- `CLAUDE.md` — convenzioni e regole permanenti del progetto
- `docs/STATO.md` — a che punto e' il lavoro
- `docs/DECISIONI.md` — le decisioni tecniche prese e il perche'
- `docs/GUIDA_STILE.md` — palette e componenti, prima di scrivere una pagina

I componenti dell'interfaccia si vedono tutti insieme, in tutte le varianti,
all'indirizzo <http://localhost:8000/stile> (serve il ruolo di creatore).
