// Menüband: der aktuelle Tab soll auch auf schmalen Bildschirmen sichtbar sein.
document.querySelector("nav.menue [aria-current]")?.scrollIntoView({inline: "center", block: "nearest"});
