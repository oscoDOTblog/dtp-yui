export const LOADING_GIFS = [
  "/imgs/gifs/160px-Base_Idle.gif",
  "/imgs/gifs/160px-Bel_Idle.gif",
  "/imgs/gifs/160px-Coil_Idle.gif",
  "/imgs/gifs/160px-DevilTheory_Idle.gif",
  "/imgs/gifs/160px-DJCyber_Idle.gif",
  "/imgs/gifs/160px-DotEXE_Idle.gif",
  "/imgs/gifs/160px-Eclipse_Idle.gif",
  "/imgs/gifs/160px-Faux_Idle.gif",
  "/imgs/gifs/160px-Felix_Idle.gif",
  "/imgs/gifs/160px-FleshPrince_Idle.gif",
  "/imgs/gifs/160px-Franks_Idle.gif",
  "/imgs/gifs/160px-Futurism_Idle.gif",
  "/imgs/gifs/160px-Jay_Idle.gif",
  "/imgs/gifs/160px-Mesh_Idle.gif",
  "/imgs/gifs/160px-Oldhead_Idle.gif",
  "/imgs/gifs/160px-Rave_Idle.gif",
  "/imgs/gifs/160px-Red_Idle.gif",
  "/imgs/gifs/160px-Rise_Idle.gif",
  "/imgs/gifs/160px-Shine_Idle.gif",
  "/imgs/gifs/160px-Solace_Idle.gif",
  "/imgs/gifs/160px-Tryce_Idle.gif",
  "/imgs/gifs/160px-Vinyl_Idle.gif",
];

export function pickRandomLoadingGif() {
  if (!LOADING_GIFS.length) return null;
  return LOADING_GIFS[Math.floor(Math.random() * LOADING_GIFS.length)];
}
