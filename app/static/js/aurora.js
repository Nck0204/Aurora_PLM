/* ==========================================================================
   Aurora - il poco JavaScript che serve all'interfaccia.

   Scritto a mano, servito dal nostro server, nessuna libreria e nessuna
   compilazione (regole 1 e 2 di CLAUDE.md). Si occupa di tre cose sole:

     1. le notifiche temporanee, che devono sparire da sole;
     2. le finestre di dialogo, che devono aprirsi e chiudersi;
     3. l'area di trascinamento dei file, che deve accorgersi del
        trascinamento.

   REGOLA CHE VALE PER TUTTO QUESTO FILE. Niente di quello che c'e' qui dentro
   e' indispensabile. Con JavaScript spento - o quando questo file non arriva
   perche' e' rimasto in una cache sbagliata - Aurora continua a funzionare:
   le notifiche restano finche' non si cambia pagina, le finestre modali non
   si aprono (e le operazioni che contano non stanno li' dentro), i file si
   scelgono con il pulsante invece che trascinandoli.

   Se un giorno qualcosa di necessario finisse qui, sarebbe un errore da
   correggere, non una scelta.

   COME SI AGGANCIA. Sempre con un attributo data-qualcosa nel template, mai
   con una classe del foglio di stile. Le classi servono all'aspetto e prima o
   poi qualcuno le rinomina: se lo script ci si appoggia, smette di funzionare
   in silenzio.
   ========================================================================== */

(function () {
    "use strict";

    /* ----------------------------------------------------------------------
       1. Notifiche temporanee

       Ogni notifica dichiara da sola quanto deve restare, nell'attributo
       data-durata (in millisecondi). Con durata 0 non sparisce: si usa per i
       messaggi lunghi da leggere.

       Il contenitore e' fisso in base.html, quindi le notifiche possono
       arrivare anche dopo, dentro un pezzo di pagina sostituito da HTMX. Per
       questo l'ascolto e' sul contenitore e non sulle singole notifiche:
       cosi' vale anche per quelle che ancora non esistono.
       -------------------------------------------------------------------- */

    var DURATA_USCITA = 200;  /* deve bastare all'animazione del CSS */

    function chiudiNotifica(notifica) {
        notifica.classList.add("notifica--in-uscita");
        window.setTimeout(function () {
            if (notifica.parentNode) {
                notifica.parentNode.removeChild(notifica);
            }
        }, DURATA_USCITA);
    }

    function programmaChiusura(notifica) {
        if (notifica.dataset.chiusuraProgrammata) {
            return;
        }
        notifica.dataset.chiusuraProgrammata = "si";

        var durata = parseInt(notifica.getAttribute("data-durata"), 10);
        if (!durata || durata <= 0) {
            return;
        }
        window.setTimeout(function () {
            chiudiNotifica(notifica);
        }, durata);
    }

    function preparaNotifiche(radice) {
        var notifiche = radice.querySelectorAll(".notifica");
        for (var i = 0; i < notifiche.length; i++) {
            programmaChiusura(notifiche[i]);
        }
    }

    var contenitoreNotifiche = document.getElementById("notifiche");
    if (contenitoreNotifiche) {
        preparaNotifiche(document);

        /* La crocetta di chiusura. L'ascolto sta sul contenitore: funziona
           anche per le notifiche aggiunte dopo. */
        contenitoreNotifiche.addEventListener("click", function (evento) {
            var chiudi = evento.target.closest(".notifica .chiudi");
            if (chiudi) {
                chiudiNotifica(chiudi.closest(".notifica"));
            }
        });

        /* Quando HTMX sostituisce un pezzo di pagina, le notifiche che
           arrivano con la risposta vanno programmate anche loro. L'evento
           esiste solo se HTMX e' stato caricato; se non c'e', questa riga non
           fa niente e non da' fastidio a nessuno. */
        document.body.addEventListener("htmx:afterSwap", function (evento) {
            preparaNotifiche(evento.target);
        });
    }

    /* ----------------------------------------------------------------------
       2. Finestre di dialogo

       Si appoggiano all'elemento <dialog> del browser, che porta gia' dentro
       il fuoco della tastiera, ce lo tiene, chiude con Esc e lo restituisce a
       chi aveva aperto. Qui si aggiungono soltanto due cose: il pulsante che
       apre (data-apre="identificatore") e quello che chiude (data-chiude).

       Il clic sullo sfondo scuro chiude anche lui. E' l'unico punto in cui
       serve un piccolo trucco: il bersaglio del clic sullo sfondo e' il
       <dialog> stesso, perche' lo sfondo (::backdrop) non e' un elemento su
       cui si possa ascoltare.
       -------------------------------------------------------------------- */

    document.addEventListener("click", function (evento) {
        var apri = evento.target.closest("[data-apre]");
        if (apri) {
            var finestra = document.getElementById(apri.getAttribute("data-apre"));
            if (finestra && typeof finestra.showModal === "function") {
                finestra.showModal();
            }
            return;
        }

        var chiudi = evento.target.closest("[data-chiude]");
        if (chiudi) {
            var daChiudere = chiudi.closest("dialog");
            if (daChiudere) {
                daChiudere.close();
            }
            return;
        }

        /* Clic sullo sfondo: il bersaglio e' il <dialog>, non il suo
           contenuto. */
        if (evento.target.tagName === "DIALOG") {
            evento.target.close();
        }
    });

    /* ----------------------------------------------------------------------
       3. Area di trascinamento dei file

       Il campo <input type="file"> c'e' gia' e funziona da solo. Qui si
       aggiunge il trascinamento e l'elenco dei file scelti.

       I quattro preventDefault() sui trascinamenti non sono decorativi: senza
       di essi il browser aprirebbe il file trascinato in una scheda nuova,
       buttando via la pagina con tutto quello che c'era scritto dentro.
       -------------------------------------------------------------------- */

    function pesoLeggibile(byte) {
        if (byte < 1024) {
            return byte + " byte";
        }
        if (byte < 1024 * 1024) {
            return Math.round(byte / 1024) + " kB";
        }
        return (byte / (1024 * 1024)).toFixed(1) + " MB";
    }

    function mostraFileScelti(area) {
        var campo = area.querySelector("input[type=file]");
        var elenco = area.querySelector("[data-area-file-elenco]");
        if (!campo || !elenco) {
            return;
        }

        elenco.innerHTML = "";

        if (!campo.files || campo.files.length === 0) {
            elenco.hidden = true;
            return;
        }

        for (var i = 0; i < campo.files.length; i++) {
            var file = campo.files[i];
            var riga = document.createElement("li");

            var nome = document.createElement("span");
            /* textContent e non innerHTML: il nome del file lo sceglie chi
               carica, e non deve poter diventare codice dentro la pagina. */
            nome.textContent = file.name;

            var peso = document.createElement("span");
            peso.className = "peso";
            peso.textContent = pesoLeggibile(file.size);

            riga.appendChild(nome);
            riga.appendChild(peso);
            elenco.appendChild(riga);
        }

        elenco.hidden = false;
    }

    var aree = document.querySelectorAll("[data-area-file]");
    for (var a = 0; a < aree.length; a++) {
        (function (area) {
            var campo = area.querySelector("input[type=file]");
            if (!campo) {
                return;
            }

            ["dragenter", "dragover", "dragleave", "drop"].forEach(function (evento) {
                area.addEventListener(evento, function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                });
            });

            ["dragenter", "dragover"].forEach(function (evento) {
                area.addEventListener(evento, function () {
                    area.classList.add("area-file--pronta");
                });
            });

            ["dragleave", "drop"].forEach(function (evento) {
                area.addEventListener(evento, function () {
                    area.classList.remove("area-file--pronta");
                });
            });

            area.addEventListener("drop", function (e) {
                if (e.dataTransfer && e.dataTransfer.files.length) {
                    /* I file trascinati si mettono dentro il campo vero: cosi'
                       li invia il modulo normale, e non serve nessuna chiamata
                       scritta a mano. */
                    campo.files = e.dataTransfer.files;
                    mostraFileScelti(area);
                }
            });

            campo.addEventListener("change", function () {
                mostraFileScelti(area);
            });
        })(aree[a]);
    }
})();
