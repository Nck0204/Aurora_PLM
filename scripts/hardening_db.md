# Irrobustimento del registro delle operazioni

Procedura da eseguire **una volta sola**, su ogni database in cui Aurora gira:
quello di sviluppo, quello di collaudo e quello di produzione. Al termine, la
tabella `audit_logs` e' a **sola aggiunta**: ci si scrivono righe nuove, non se
ne modifica e non se ne toglie nessuna.

Lo script e' `scripts/hardening_db.sql`. Questo file dice come eseguirlo, che
cosa deve succedere e come verificare che sia successo davvero.

> **Situazione su questo computer (verificata il 26/08/2026)**
> La **parte 1** e' stata applicata: `aurora_app` ha su `audit_logs` i soli
> permessi `SELECT` e `INSERT`, e un `UPDATE` con le credenziali di Aurora
> fallisce. La **parte 2** - proprietario separato e grilletti - richiede la
> password dell'utente `postgres` e resta da fare: e' il passo 3 qui sotto.

---

## 1. Perche' si fa

In `app/services/audit.py` c'e' una funzione sola che scrive nel registro, e
non ce n'e' nessuna che lo corregge. E' vero oggi. Potrebbe non esserlo fra due
anni: basta che qualcuno aggiunga una funzione "per sistemare una riga
sbagliata" e la garanzia sparisce senza che nessuno se ne accorga.

Un permesso che fa rispettare il database non si dimentica. Dopo questa
procedura il programma **non riesce** a correggere una riga del registro
nemmeno provandoci, e chi verifica Aurora non deve fidarsi della parola di chi
l'ha scritta: puo' aprire `psql` e guardare i permessi.

Gli strati sono quattro e fanno quattro cose diverse:

| Strato | Che cosa ferma | Dove sta |
|---|---|---|
| I permessi | il programma, compreso il programma sbagliato di domani | parte 1 dello script |
| Il proprietario separato | il programma che si ridarebbe i permessi da solo | parte 2 dello script |
| I grilletti | lo sbaglio di chi amministra il database | parte 2 dello script |
| La catena di impronte | niente: **rende visibile** la manomissione riuscita | `app/services/audit.py` |

L'ultimo e' l'unico che serva contro chi vuole davvero manomettere il registro
e ha le credenziali per farlo: un superutente di PostgreSQL puo' disattivare un
grilletto e riassegnare un permesso. Non puo' pero' rifare le impronte di tutte
le voci successive senza rifarle una per una, e `scripts/verifica_audit.py` se
ne accorge. Vedi `docs/DECISIONI.md`, D-063.

---

## 2. Quando si fa

**Dopo `alembic upgrade head`, e mai prima.**

La migrazione `e2f5a91c73d8` riempie le colonne nuove delle righe che ci sono
gia': e' un `UPDATE` su `audit_logs`, ed e' l'ultimo che verra' mai eseguito su
quella tabella. Applicando prima i permessi, la migrazione fallirebbe con un
"permesso negato".

Vale anche per il futuro: se un giorno una migrazione dovra' toccare
`audit_logs`, andra' eseguita da `aurora_owner` o da `postgres`, non da
`aurora_app`. E' il prezzo di avere un registro che il programma non puo'
correggere, e va pagato consapevolmente.

---

## 3. Come si esegue

### Passo 1 - Applicare le migrazioni

Dalla radice del progetto, con l'ambiente virtuale attivo:

```powershell
alembic upgrade head
```

### Passo 2 - Fare una copia del database

Non e' un passo facoltativo. Lo script cambia il proprietario di una tabella e
concede permessi: se qualcosa va storto si vuole poter tornare indietro.

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -h localhost -d aurora -F c -f aurora-prima-hardening.dump
```

### Passo 3 - Eseguire lo script come `postgres`

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d aurora -f scripts\hardening_db.sql
```

Viene chiesta la password dell'utente `postgres`, quella scelta durante
l'installazione di PostgreSQL. **Mentre si scrive non compare nulla a schermo:
e' normale.**

Lo script stampa quello che fa, e in fondo stampa quello che e' rimasto. Deve
finire cosi':

```
 permesso
----------
 INSERT
 SELECT
(2 righe)

 proprietario
--------------
 aurora_owner

 grilletto
------------------------------
 audit_logs_niente_modifiche
 audit_logs_niente_svuotamento
```

Se nella prima tabella compare anche `UPDATE` o `DELETE`, qualcosa non ha
funzionato: rileggere i messaggi piu' sopra.

Se compare il messaggio `--- PARTE 2 SALTATA ---`, lo script e' stato eseguito
con un utente che non e' superutente. La parte 1 - i permessi - e' comunque
stata applicata; per completare, rieseguirlo come `postgres`.

Lo script si puo' **rieseguire quante volte si vuole**: e' scritto per non
lamentarsi di trovare il lavoro gia' fatto.

---

## 4. Verifica

E' la parte che conta. I permessi si stampano da soli, ma la prova vera e'
provare a fare quello che non si deve poter fare.

### 4.1 Un UPDATE con le credenziali di Aurora deve fallire

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U aurora_app -h localhost -d aurora -c "UPDATE audit_logs SET description = 'manomesso' WHERE seq = 1;"
```

Risposta attesa:

```
ERRORE:  permesso negato per la tabella audit_logs
```

Se invece risponde `UPDATE 1`, la procedura **non e' stata applicata**: la riga
e' stata cambiata davvero, e va rimessa a posto ripristinando la copia del
passo 2.

### 4.2 Anche DELETE e TRUNCATE devono fallire

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U aurora_app -h localhost -d aurora -c "DELETE FROM audit_logs WHERE seq = 1;"
```

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U aurora_app -h localhost -d aurora -c "TRUNCATE audit_logs;"
```

Tutti e due: `permesso negato per la tabella audit_logs`.

### 4.3 Aurora deve continuare a funzionare

Il registro deve restare **leggibile** e **scrivibile in aggiunta**. Si
verifica usando Aurora:

1. avviare il server (`uvicorn app.main:app --reload`);
2. entrare: e' un'operazione che scrive nel registro;
3. aprire <http://localhost:8000/registro> e controllare che l'accesso appena
   fatto sia in cima all'elenco.

Se l'accesso non riesce con un errore di permessi, la parte 1 dello script ha
tolto piu' del dovuto: rieseguirlo.

### 4.4 La catena e' integra

```powershell
python scripts\verifica_audit.py
```

Deve rispondere che la catena e' integra. Vedi la procedura completa in fondo a
quel file.

---

## 5. Che cosa cambia per chi mantiene Aurora

**Le migrazioni che toccano `audit_logs` vanno eseguite come `postgres`.**
Aggiungere una colonna a quella tabella e' un `ALTER TABLE`, e dopo il passo 3
`aurora_app` non e' piu' il proprietario. In pratica:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:PASSWORD@localhost:5432/aurora"
alembic upgrade head
```

e poi si rimette la variabile com'era (o si chiude quella finestra di
PowerShell: la variabile vale solo li' dentro).

**Le voci del registro non si cancellano mai**, nemmeno le piu' vecchie. La
politica di conservazione e' l'archiviazione, non la cancellazione: vedi
`scripts/archivia_audit.py`, che scrive un file compresso e **non tocca il
database**.

---

## 6. Come si torna indietro

Serve solo in due casi: un guasto durante la procedura, oppure una migrazione
futura che debba modificare le righe gia' scritte. Da eseguire come `postgres`,
sul database `aurora`:

```sql
ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_niente_modifiche;
```

```sql
GRANT UPDATE, DELETE ON TABLE audit_logs TO aurora_app;
```

**E si rimette tutto subito dopo**, rieseguendo `scripts/hardening_db.sql`. Un
registro lasciato modificabile "per un momento" e' un registro modificabile.

Il fatto che qualcuno abbia dovuto fare questo va scritto da qualche parte che
non sia il registro stesso: la finestra in cui i grilletti erano spenti e'
esattamente la finestra in cui il registro non dimostra piu' niente.
