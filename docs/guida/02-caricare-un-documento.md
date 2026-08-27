# Caricare un documento

Un documento in Aurora sta sempre dentro un progetto, ha sempre una
classificazione e ha sempre almeno una versione. Non si carica un file "e
basta": si carica un file dicendo di che cosa fa parte e chi lo puo' vedere.

## Il giro completo, in cinque campi

Si apre il progetto, si preme **Carica un documento** e si compilano cinque
cose.

**Il titolo.** Come lo chiamano le persone, non come si chiama il file.
"Schema elettrico scheda alimentazione" e' un titolo; `SCH_REV3_final_ok.pdf`
non lo e'. Il nome del file resta scritto da qualche parte e si ritrova, ma non
e' quello che si legge negli elenchi.

**Il tipo.** Schema elettrico, PCB, distinta base, firmware, certificato. E' un
elenco che l'azienda puo' cambiare senza toccare il programma.

**La classificazione.** Tecnico, Commerciale, Qualita', Amministrativo. **E'
questa a decidere chi vedra' il documento**, quindi e' il campo su cui vale la
pena fermarsi un secondo: un'offerta messa fra i documenti tecnici la vedranno
tutti gli ingegneri del progetto.

**Il file.** Si trascina dentro il riquadro, oppure si sceglie con il pulsante.
Mentre parte si vede una barra con i byte spediti davvero: su un file da
duecento megabyte serve a sapere che sta succedendo qualcosa.

**La nota.** Obbligatoria. Vedi la sezione qui sotto.

## La nota e' obbligatoria, e non e' una formalita'

Ogni versione caricata vuole una nota che dica **che cosa e' cambiato rispetto
alla precedente**. Sulla prima versione basta dire che cos'e'.

Sembra una seccatura e non lo e': fra due anni, davanti a una revisione 7,
l'unica cosa che permette di capire perche' esiste la 5 e' quello che qualcuno
ha scritto quel giorno in tre righe. Il file non lo dice, la data non lo dice,
il nome del file men che meno.

Una nota utile dice **la modifica e il motivo**:

> Corretto il valore di R12 da 4k7 a 10k dopo la prova di compatibilita'
> elettromagnetica del 12 marzo.

Una nota inutile dice "aggiornamento".

## Caricare una versione nuova

Si apre il documento e si preme **Carica una versione**. Il numero lo mette
Aurora: la 1 diventa la 2, la 2 la 3. Non c'e' modo di saltare un numero e non
c'e' modo di riusarlo.

**Non esiste un modo di sostituire il file di una versione gia' caricata.** Non
e' una funzione che manca: e' una funzione che non ci sara' mai. Una versione
caricata e' un fatto avvenuto - qualcuno l'ha scaricata, qualcuno ci ha
lavorato sopra - e riscriverla vorrebbe dire cambiare il passato. Se il file
era sbagliato se ne carica un altro, con la nota che dice che il precedente
era sbagliato.

## Lo stesso file caricato due volte

Non occupa spazio due volte. Aurora riconosce un contenuto gia' presente e non
lo riscrive, ma le due righe restano due righe distinte: due documenti diversi
possono avere lo stesso allegato senza che nessuno se ne accorga.

## Se un documento e' sbagliato o non serve piu'

Si **ritira**, non si cancella. Un documento ritirato sparisce dagli elenchi e
resta nel programma: chi amministra Aurora lo puo' rivedere e rimettere a
posto. Non esiste nessun modo di cancellare davvero un documento, e il file
sull'archivio resta dov'e'.

## Scaricare

Ogni scarico lascia una riga nel registro: chi, che cosa, quando. Non e' una
sorveglianza sulle persone, e' la risposta alla domanda che prima o poi arriva:
*"chi aveva la revisione 3 quando e' partita in produzione?"*.

I PDF delle **versioni superate** si scaricano con una filigrana in
trasparenza che lo dice. E' l'unica volta in cui Aurora modifica un file, e lo
fa mentre te lo manda: l'originale nell'archivio resta intatto.
