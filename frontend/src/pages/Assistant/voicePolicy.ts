/** Speech privacy policy: loopback audio processing and explicitly local voices only. */
export function localSpeechEndpoint(base: string | undefined, page: string): boolean {
  try {
    const url = new URL(base ?? '/api/v1', page);
    return ['http:', 'https:'].includes(url.protocol)
      && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && !url.username && !url.password;
  } catch { return false; }
}
export function localEnglishVoice<T extends { lang: string; localService: boolean }>(voices: T[]): T | undefined {
  return voices.find(voice => voice.localService === true && /^en(?:-|$)/i.test(voice.lang));
}

export function localVoice<T extends {lang:string;localService:boolean}>(voices:T[],language:string):T|undefined {
  return voices.find(voice=>voice.localService===true && voice.lang.toLowerCase().split('-')[0]===language);
}
