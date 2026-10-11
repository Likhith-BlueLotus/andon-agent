/** The demo passcode lives in module memory only: never in a URL, localStorage or sessionStorage. Shared by the console and the upload page. */
let current: string | null = null;
export const getPasscode = (): string | null => current;
export const setPasscode = (p: string | null): void => {
  current = p;
};
