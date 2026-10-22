"""Extract explicit what-if inputs and bounded follow-ups from local multilingual chat."""
import re
from datetime import date
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .c2_gateway import Numeric, Reference

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
REF = re.compile(r'(?<![A-Za-z0-9_])A[A-Za-z0-9_-]{1,159}(?![A-Za-z0-9_-])')
THI = re.compile(r'(?<![a-z0-9_])thi(?![a-z0-9_])', re.I)
MILKINGS = re.compile(r'\bmilkings?(?:\s*(?:/|per|a)\s*day)?\b|\bmilking\s+frequency\b|කිරි\s*දෙවීම්|දෙවීම්|දොවන\s*වාර|கறவை(?:\s*எண்ணிக்கை)?|கறக்கும்\s*முறை', re.I)
SMALL_NUMBERS = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,
    'එක':1,'දෙක':2,'තුන':3,'හතර':4,'දෙවරක්':2,'තෙවරක්':3,'තුන්වරක්':3,
    'ஒன்று':1,'ஒரு':1,'இரண்டு':2,'மூன்று':3,'நான்கு':4}
VALUE = NUMBER + r'|' + '|'.join(sorted(SMALL_NUMBERS, key=len, reverse=True))
CAUSAL = re.compile(r'\b(why|cause|caused|diagnos\w*|treat\w*)\b|ඇයි|හේතුව|හේතු|රෝග\s*නිර්ණ|ප්‍රතිකාර|ஏன்|காரண|நோயறி|சிகிச்சை', re.I)
FEED = re.compile(r'\b(feed(?:ing)?|concentrate|supplements?|ration|diet)\b|ආහාර|සාන්ද්‍ර|தீவன|உணவ', re.I)
CANCEL = re.compile(r'^\s*(?:cancel|stop|never\s*mind|cancel\s+(?:that|the\s+scenario)|අවලංගු\s*කරන්න|නවත්වන්න|ரத்து\s*செய்|நிறுத்து)[.!?\s]*$', re.I)


class ScenarioDraft(BaseModel):
    """Proposed user inputs only, never observed farm facts or tool instructions."""
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    animal_ref: Reference | None = None
    thi_mean: Numeric | None = None
    milkings_per_day: Numeric | None = Field(default=None, gt=0)
    mode: Literal['thi', 'milkings', 'combined'] | None = None


def ascii_digits(text):
    return ''.join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in text)


def simulation_intent(text):
    text = ascii_digits(text)
    return bool(re.search(r'\b(?:c2|simulat\w*|what[- ]if|increase|decrease)\b|'
        r'\b(?:what|how\s+much)\b.{0,80}\bif\b.{0,150}(?:\bthi\b|\bmilkings?\b|\bmilk\b.{0,80}\btimes\b)|'
        r'\bif\b.{0,200}(?:\bthi\b|\bmilkings?\b|\bmilk\b.{0,100}\btimes\b)|'
        r'අනුකරණ|කළොත්|වුණොත්|වුවහොත්|දොවනවා\s*නම්|'
        r'உருவகப்படுத்த|அதிகரித்தால்|குறைத்தால்|மாற்றினால்|கறந்தால்', text, re.I))


def number(token):
    return float(SMALL_NUMBERS[token.lower()]) if token.lower() in SMALL_NUMBERS else float(token)


def extract(text):
    """Numbers must be next to a named feature; mask dates and reference digits first."""
    text = ascii_digits(text)
    references = list(dict.fromkeys(REF.findall(text)))
    clean = REF.sub(' ', text)
    clean = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', clean)
    labels = sorted([(m.start(),m.end(),'thi_mean') for m in THI.finditer(clean)] +
                    [(m.start(),m.end(),'milkings_per_day') for m in MILKINGS.finditer(clean)])
    mentioned = {key for _,_,key in labels}
    candidates = {}; issues = set()
    if re.search(r'%|\b(?:percent|percentage)\b|\bby\s+'+NUMBER+r'|සියයට|சதவீத',clean,re.I):issues.add('relative')
    for index,(start,end,key) in enumerate(labels):
        segment = clean[end:labels[index+1][0] if index+1<len(labels) else end+100]
        # A relative change requires an absolute target; never silently reuse an old value.
        if re.match(r'\s*(?:(?:is|changes?|increases?|decreases?|reduced|lowered)\s+)?(?:by|%|percent|සියයට|சதவீத)',segment,re.I):
            issues.add('relative');candidates.setdefault(key,[]);continue
        match = re.match(r'\s*(?:(?:is|decreases?|drops?|reduces?|reduced|lowered|changes?|changed)\s+)?(?:from\s+)?('+NUMBER+r')\s*(?:to|සිට|இலிருந்து)\s*('+NUMBER+r')',segment,re.I)
        if match:
            candidates.setdefault(key,[]).append(number(match[2]));continue
        if re.match(r'\s*(?:(?:is|decreases?|drops?|reduces?|reduced|lowered|changes?|changed)\s+)?from\b',segment,re.I):
            issues.add('ambiguous');continue
        # Literal numeric / small-number-word targets with common language particles.
        prefix = r'(?:\s|[:=,]|\b(?:to|at|is|be|becomes|of|set|changes?|changed|drops?|dropped|reduces?|reduced|lowered|from)\b|අගය|එක|මට්ටම|ஐ|யை|மதிப்பு|அளவு)*'
        match = re.match(prefix+'('+VALUE+r')(?![\d.])',segment,re.I)
        if match:
            after = segment[match.end():]
            if re.match(r'\s*(?:%|percent|සියයට|சதவீத)',after,re.I):issues.add('relative');continue
            if re.match(r'\s*(?:or|vs\.?|versus|හෝ|அல்லது)\s*'+NUMBER,after,re.I):issues.add('ambiguous');continue
            candidates.setdefault(key,[]).append(number(match[1]))
    # Natural frequency wording: "milk her three times a day", "3 milkings per day".
    frequency = re.compile(r'(?<![\w.])('+VALUE+r')\s*(?:times\s*(?:a|per|each)\s*day|milkings?\s*(?:a|per|/)\s*day|වරක්|முறை)',re.I)
    for match in frequency.finditer(clean):
        mentioned.add('milkings_per_day')
        candidates.setdefault('milkings_per_day',[]).append(number(match[1]))
    for word in ('දෙවරක්','තෙවරක්','තුන්වරක්'):
        if word in clean:
            mentioned.add('milkings_per_day');candidates.setdefault('milkings_per_day',[]).append(number(word))
    values = {}
    for key,items in candidates.items():
        unique = set(items)
        if len(unique)>1:issues.add('ambiguous')
        elif unique:values[key]=unique.pop()
    if not references:
        # An explicit unrecognised cow must never fall back to the preceding cow.
        unknown = re.search(r'\b(?:for|use|using|with)\s+(?:cow|animal)\s+([A-Za-z0-9_-]+)',text,re.I)
        numbered = re.search(r'\b(?:cow|animal)\s*#?\s*\d+\b',text,re.I)
        if numbered or (unknown and unknown[1].lower() not in {'with','at','the','a','same','reference','thi'}):issues.add('cow')
    if len(references)>1:issues.add('cow')
    if references==['A_PLACEHOLDER']:issues.add('cow');references=[]
    if len(mentioned)==2 and re.search(r'\b(?:or|either)\b|හෝ|அல்லது',clean,re.I):issues.add('choice')
    return dict(references=references,mentioned=mentioned,values=values,issues=issues)


def reference_reply(text, context):
    """Recognize a complete pasted list label only in an existing simulation dialogue.

    The list date is display metadata, never a user-selected simulation date.
    Arbitrary suffixes, multiple references and invalid dates are not stripped.
    """
    if context.topic != 'simulation' or context.scenario is None:
        return text
    match = re.fullmatch(r'\s*(A[A-Za-z0-9_-]{1,159})\s*[·•]\s*latest record\s+(\d{4}-\d{2}-\d{2})\s*', text, re.I)
    if match and REF.fullmatch(match[1]) and match[1] != 'A_PLACEHOLDER':
        try:
            date.fromisoformat(match[2])
        except ValueError:
            return text
        return match[1]
    return text


def general_request(text):
    """An explicit general scope takes precedence over a remembered animal."""
    return bool(re.search(r'\b(?:in general|generally|generic|farm[- ]wide|for the farm|'
        r'without (?:a |any |a specific )?(?:cow|animal)|no specific cow)\b|සාමාන්‍ය|பொதுவா', text, re.I))


def individual_request(text):
    """Only an explicit individual request starts a cow-reference clarification."""
    return bool(re.search(r'\b(?:individual|specific|single|selected|one)\s+(?:cow|animal)\b|'
                          r'එක්\s*ගව|තනි\s*ගව|ஒரு\s*பசு|தனிப்பட்ட\s*பசு', text, re.I))


def is_followup(text, context):
    if context.topic!='simulation' or context.scenario is None:return False
    text=reference_reply(text,context)
    if CANCEL.fullmatch(text) or re.fullmatch(r"\s*(?:do not|don't)\s+run[.!?\s]*",text,re.I):return True
    data=extract(text)
    # Explicit requests for another data source switch topic instead of running C2.
    if re.search(r'\b(?:historical|recorded|weather|forecast|risk|herd\s+summary)\b|කාලගුණ|පුරෝකථ|අවදාන|வானிலை|முன்னறிவி|அபாய',text,re.I) and not simulation_intent(text):return False
    if re.search(r'\b(?:milk\s+(?:summary|comparison)|production\s+summary)\b',text,re.I) and not simulation_intent(text):return False
    if general_request(text):return True
    if data['mentioned']:return True
    without_refs=REF.sub('',text).strip(' .!?\t\r\n')
    if data['references'] and (not without_refs or re.fullmatch(r"(?:cow|animal|reference|it'?s|use|for|the|ගවයා|ගව|பசு|குறிப்பு|\s)+",without_refs,re.I)):return True
    if context.awaiting in ('simulation_thi','simulation_milkings','simulation_value') and re.fullmatch(r'\s*(?:'+VALUE+r')[.!?\s]*',ascii_digits(text),re.I):return True
    return bool(re.fullmatch(r'\s*(?:thi|milkings?|milking\s+frequency|both|combined|කිරි\s*දෙවීම්|දෙකම|கறவை|இரண்டும்)[.!?\s]*',text,re.I))


def advance(text, previous, awaiting):
    """Retain only bounded input context; ambiguity clears the affected targets."""
    data=extract(text);draft=previous.model_copy(deep=True) if previous else ScenarioDraft()
    refs=data['references'];mentioned=data['mentioned'];values=data['values'];issues=data['issues']
    if 'cow' in issues:draft.animal_ref=None
    elif refs:draft.animal_ref=refs[0]
    elif re.search(r'\b(?:another|different)\s+cow\b|වෙනත්\s*ගව|வேறு\s*பசு',text,re.I):draft.animal_ref=None
    if not mentioned and re.fullmatch(r'\s*(?:both|combined|දෙකම|இரண்டும்)[.!?\s]*',text,re.I):mentioned={'thi_mean','milkings_per_day'}
    if not mentioned and re.fullmatch(r'\s*(?:'+VALUE+r')[.!?\s]*',ascii_digits(text),re.I):
        field={'simulation_thi':'thi_mean','simulation_milkings':'milkings_per_day'}.get(awaiting)
        if field:
            mentioned={field};values[field]=number(re.match(r'\s*('+VALUE+r')',ascii_digits(text),re.I)[1])
        else:issues.add('ambiguous')
    continuation=bool(re.search(r'^\s*(?:and|also|with|same|keep)\b|එම|එකම|සමඟ|அதே|மேலும்|உடன்',text,re.I))
    if 'choice' in issues:draft.mode=None;draft.thi_mean=None;draft.milkings_per_day=None
    elif len(mentioned)==2:draft.mode='combined'
    elif mentioned:
        key=next(iter(mentioned));other='milkings_per_day' if key=='thi_mean' else 'thi_mean'
        keep_combined=(draft.mode=='combined' and awaiting in ('simulation_thi','simulation_milkings')) or (continuation and getattr(draft,other) is not None)
        draft.mode='combined' if keep_combined else 'thi' if key=='thi_mean' else 'milkings'
        if not keep_combined:setattr(draft,other,None)
    for key in mentioned:
        # Never keep a stale value when the user asks an ambiguous/relative revision.
        if issues.intersection({'relative','ambiguous','choice'}):setattr(draft,key,None)
        elif key in values:setattr(draft,key,values[key])
        elif not continuation:setattr(draft,key,None)
    if issues.intersection({'relative','ambiguous'}) and not mentioned:
        draft.thi_mean=None;draft.milkings_per_day=None;draft.mode=None
    if draft.milkings_per_day is not None and draft.milkings_per_day<=0:
        draft.milkings_per_day=None;issues.add('invalid')
    # Validate proposed numbers again (including overflows) before retaining context.
    try:draft=ScenarioDraft.model_validate(draft.model_dump())
    except ValueError:
        draft.thi_mean=None;draft.milkings_per_day=None;issues.add('invalid')
    missing=[]
    if draft.animal_ref is None:missing.append('animal_ref')
    if draft.mode is None:missing.append('scenario_value')
    elif draft.mode in ('thi','combined') and draft.thi_mean is None:missing.append('thi_mean')
    if draft.mode in ('milkings','combined') and draft.milkings_per_day is None:missing.append('milkings_per_day')
    return draft,missing,issues
