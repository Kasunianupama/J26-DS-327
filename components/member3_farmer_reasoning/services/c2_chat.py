"""C3 automatically orchestrates C2 from explicit user wording and bounded chat context."""
import re
from .c2_gateway import C2Unavailable, ScenarioInput, simulate
from .c2_dialogue import ScenarioDraft, advance, extract, CANCEL, CAUSAL, FEED, ascii_digits, individual_request, general_request


def reply(request, context, *, invoke=None, query_text=None):
    text = ascii_digits(query_text if query_text is not None else request.query)
    result = dict(tool='c2_simulation', provider='local_template', cloud_processing=False,
        demo=False, title='What-if simulation')
    cancelled = CANCEL.fullmatch(text) or re.search(r"\b(?:do not|don't|never)\s+(?:run|simulate|call|execute)\b|අනුකරණ.*එපා|இயக்க.*வேண்டாம்",text,re.I)
    if cancelled:
        context.scenario=None;context.awaiting=None
        result.update(status='cancelled',simulation_state='cancelled')
    elif FEED.search(text):
        context.scenario=None;context.awaiting=None
        result.update(status='unsupported',simulation_state='unsupported')
    elif CAUSAL.search(text):
        context.scenario=None;context.awaiting=None
        result.update(status='unsupported',simulation_state='causal')
    elif re.search(r'\b(?:all|whole)\s+(?:cows|herd)|මුළු\s*රංචුව|සියලු\s*ගව|அனைத்து\s*பசு|முழு\s*மந்தை',text,re.I):
        context.scenario=None;context.awaiting=None
        result.update(status='unsupported',simulation_state='cow_scope')
    elif request.reference_date or request.target_period or re.search(r'\d{4}-\d{2}-\d{2}',text):
        context.awaiting=None
        result.update(status='unsupported',simulation_state='invalid_dates')
    elif re.search(r'\b(?:week|month|weekly|monthly)\b|සති|මාස|வார|மாதம்|மாதாந்திர|மாதங்களுக்கு|மாதங்கள்',text,re.I) or re.search(r'\b(?:two|three|four|five|six|seven|eight)\s+days?\b',text,re.I) or any(int(value)!=1 for match in re.findall(r'\b(\d+)\s*days?\b|(?:(?:දින|நாட்கள்|நாள்)\s*(\d+))|(?:(\d+)\s*(?:දින|நாட்கள்|நாள்))',text,re.I) for value in (match if isinstance(match,tuple) else (match,)) if value):
        context.scenario=None;context.awaiting=None
        result.update(status='unsupported',simulation_state='horizon')
    elif general_request(text):
        draft,_,_=advance(text,None,None)
        draft.animal_ref=None
        context.scenario=draft;context.awaiting=None
        result.update(status='information',simulation_state='general',title='Considering a change')
    else:
        explicit=request.simulation
        if explicit is not None:
            parsed=extract(text)
            conflict=(len(parsed['references'])>1 or (parsed['references'] and parsed['references'][0]!=explicit.animal_ref)
                or any(getattr(explicit,key)!=value for key,value in parsed['values'].items()) or parsed['issues'])
            if conflict:
                draft,missing,issues=advance(text,None,None)
                missing=['scenario_value'];issues={'ambiguous'}
                draft.thi_mean=None;draft.milkings_per_day=None
            else:
                draft=ScenarioDraft(animal_ref=explicit.animal_ref,thi_mean=explicit.thi_mean,milkings_per_day=explicit.milkings_per_day,
                    mode='combined' if explicit.thi_mean is not None and explicit.milkings_per_day is not None else 'thi' if explicit.thi_mean is not None else 'milkings')
                missing=[];issues=set()
        else:
            draft,missing,issues=advance(text,context.scenario,context.awaiting)
        context.scenario=draft
        if draft.animal_ref is None and explicit is None and 'cow' not in issues and not individual_request(text):
            # A broad question receives an explanation, never a guessed animal
            # or an invented herd prediction. Retain only explicit proposed inputs.
            context.awaiting=None
            result.update(status='information',simulation_state='general',title='Considering a change')
        elif missing or issues:
            slot={'animal_ref':'simulation_cow','thi_mean':'simulation_thi','milkings_per_day':'simulation_milkings','scenario_value':'simulation_value'}
            first_missing=missing[0] if missing else 'scenario_value'
            if issues.intersection({'relative','ambiguous','invalid'}):
                first_missing=next((key for key in ('thi_mean','milkings_per_day') if key in missing),'scenario_value')
            context.awaiting='simulation_feature' if 'choice' in issues else slot.get(first_missing,'simulation_value')
            result.update(status='needs_input',simulation_state='needs_input',missing_fields=missing,
                clarification=next((key for key in ('cow','relative','ambiguous','choice','invalid') if key in issues),None))
        else:
            context.awaiting=None
            arguments=ScenarioInput(animal_ref=draft.animal_ref,thi_mean=draft.thi_mean,milkings_per_day=draft.milkings_per_day)
            try:
                outcome=simulate(arguments,invoke=invoke)
                result.update(status='success' if outcome['available'] else 'unavailable',
                    simulation_state='ready' if outcome['available'] else 'not_ready',
                    evidence=outcome['evidence'],warnings=outcome['warnings'])
            except C2Unavailable:
                result.update(status='unavailable',simulation_state='api_unavailable')
            except Exception:
                result.update(status='unavailable',simulation_state='invalid_evidence')
    result['context']=context.model_dump(mode='json')
    result['answer']=explain(result,'en')
    return result


def explain(result, language):
    def pick(en, si, ta):
        return {'en': en, 'si': si, 'ta': ta}[language]
    state = result['simulation_state']
    if state == 'general':
        mode=(result.get('context',{}).get('scenario') or {}).get('mode')
        intro=pick('What this comparison can tell you:', 'මෙම සංසන්දනයෙන් දැනගත හැකි දේ:', 'இந்த ஒப்பீடு தெரிவிப்பது:')
        if mode == 'thi':
            detail=pick('This scenario compares different heat-exposure inputs while keeping the recorded baseline the same. It does not calculate the effect or cost of a particular cooling system.',
                'මෙම තත්ත්වය වාර්තාගත මූලික තත්ත්වය එලෙසම තබා විවිධ තාප නිරාවරණ ආදාන සසඳයි. විශේෂ සිසිලන පද්ධතියක බලපෑම හෝ වියදම මෙයින් ගණනය නොවේ.',
                'இந்தச் சூழல் பதிவான அடிப்படையை மாற்றாமல் வெவ்வேறு வெப்ப வெளிப்பாட்டு உள்ளீடுகளை ஒப்பிடுகிறது. குறிப்பிட்ட குளிர்விப்பு அமைப்பின் விளைவையோ செலவையோ கணக்கிடாது.')
        elif mode == 'milkings':
            detail=pick('This scenario compares a proposed milking frequency with the recorded baseline. It does not establish whether the change is practical or what it would cost.',
                'මෙම තත්ත්වය යෝජිත කිරි දෙවීම් වාර ගණන වාර්තාගත මූලික තත්ත්වය සමඟ සසඳයි. වෙනස ක්‍රියාත්මක කළ හැකිද හෝ එහි වියදම කුමක්ද යන්න මෙයින් තහවුරු නොවේ.',
                'இந்தச் சூழல் முன்மொழியும் கறவை எண்ணிக்கையை பதிவான அடிப்படையுடன் ஒப்பிடுகிறது. மாற்றம் நடைமுறைக்கு ஏற்றதா அல்லது அதன் செலவு என்ன என்பதை உறுதிப்படுத்தாது.')
        else:
            detail=pick('The available simulator compares heat-exposure and milking-frequency inputs against a recorded baseline. A changed input alone does not establish a production benefit.',
                'පවතින අනුකාරකය තාප නිරාවරණය සහ කිරි දෙවීම් වාර ගණන වාර්තාගත මූලික තත්ත්වය සමඟ සසඳයි. ආදානයක් වෙනස් කිරීම පමණින් නිෂ්පාදන ප්‍රතිලාභයක් තහවුරු නොවේ.',
                'கிடைக்கும் உருவகப்படுத்தி வெப்ப வெளிப்பாடு மற்றும் கறவை எண்ணிக்கையை பதிவான அடிப்படையுடன் ஒப்பிடுகிறது. உள்ளீடு மாறுவது மட்டுமே உற்பத்திப் பயனை நிரூபிக்காது.')
        limits=pick('For your farm:', 'ඔබේ ගොවිපළ සඳහා:', 'உங்கள் பண்ணைக்கு:')+'\n'+pick(
            'A numerical effect for the whole farm is not available from this model. I can show recorded farm milk comparisons or stored forecasts as background, but cannot present them as the effect of this proposed change.',
            'මෙම ආකෘතියෙන් මුළු ගොවිපළට අදාළ සංඛ්‍යාත්මක බලපෑමක් ලබා ගත නොහැක. පසුබිම ලෙස වාර්තාගත කිරි සංසන්දන හෝ ගබඩා කළ පුරෝකථන පෙන්විය හැකි නමුත් ඒවා යෝජිත වෙනසේ ප්‍රතිඵල ලෙස දැක්විය නොහැක.',
            'இந்த மாதிரி முழுப் பண்ணைக்கான எண்ணியல் விளைவை வழங்காது. பின்னணியாக பதிவான பால் ஒப்பீடுகளையோ சேமித்த முன்னறிவிப்புகளையோ காட்டலாம்; அவற்றை இந்த மாற்றத்தின் விளைவாகக் காட்ட முடியாது.')
        optional=pick('Optional individual estimate:', 'අවශ්‍ය නම් තනි ගව ඇස්තමේන්තුවක්:', 'விரும்பினால் தனிப் பசு மதிப்பீடு:')+'\n'+pick(
            'If you want a numerical estimate for one selected cow, ask for an individual simulation. General questions do not require a cow reference. No simulation was run for this explanation.',
            'තෝරාගත් එක් ගවයෙකු සඳහා සංඛ්‍යාත්මක ඇස්තමේන්තුවක් අවශ්‍ය නම් තනි ගව අනුකරණයක් ඉල්ලන්න. සාමාන්‍ය ප්‍රශ්න සඳහා ගව හැඳුනුමක් අවශ්‍ය නැත. මෙම පැහැදිලි කිරීම සඳහා අනුකරණයක් ක්‍රියාත්මක කර නැත.',
            'தேர்ந்தெடுத்த ஒரு பசுவிற்கு எண்ணியல் மதிப்பீடு வேண்டுமெனில் தனிப் பசு உருவகப்படுத்தலைக் கேளுங்கள். பொதுவான கேள்விகளுக்கு பசுக் குறிப்பு தேவையில்லை. இந்த விளக்கத்திற்கு உருவகப்படுத்தல் இயக்கப்படவில்லை.')
        return intro+'\n'+detail+'\n\n'+limits+'\n\n'+optional
    if state == 'needs_input':
        issue=result.get('clarification')
        if issue=='cow':
            return pick('Which one approved cow should I use? Please provide a single cow reference; I cannot select a different cow or the placeholder automatically.',
                'කුමන අනුමත ගවයා භාවිතා කළ යුතුද? එක් ගව හැඳුනුමක් දෙන්න. වෙනත් ගවයෙකු හෝ ආදේශක සතෙකු ස්වයංක්‍රීයව තෝරාගත නොහැක.',
                'எந்த ஒரு அங்கீகரிக்கப்பட்ட பசுவைப் பயன்படுத்த வேண்டும்? ஒரு பசுக் குறிப்பைத் தரவும். வேறொரு பசுவையோ இடநிரப்பியையோ தானாகத் தேர்ந்தெடுக்க முடியாது.')
        if issue=='relative':
            return pick('What absolute THI or milkings-per-day value should I test? A percentage or relative change is not an absolute scenario input. I will run the supported model automatically once the cow and target values are clear.',
                'පරීක්ෂා කළ යුතු නිරපේක්ෂ THI හෝ දෛනික කිරි දෙවීම් අගය කුමක්ද? ප්‍රතිශතයක් හෝ සාපේක්ෂ වෙනසක් නිරපේක්ෂ ආදානයක් නොවේ. ගවයා සහ ඉලක්ක අගයන් පැහැදිලි වූ පසු ආකෘතිය ස්වයංක්‍රීයව ක්‍රියාත්මක කරමි.',
                'எந்த முழுமையான THI அல்லது தினசரி கறவை எண்ணிக்கையைச் சோதிக்க வேண்டும்? சதவீதமோ சார்பு மாற்றமோ முழுமையான உள்ளீடல்ல. பசுவும் இலக்கு மதிப்புகளும் தெளிவானதும் மாதிரியைத் தானாக இயக்குவேன்.')
        if issue in ('ambiguous','invalid'):
            return pick('Please clarify the proposed values: label one absolute THI and/or one positive milkings-per-day value. I will not guess between alternatives or use an invalid number.',
                'යෝජිත අගයන් පැහැදිලි කරන්න. එක් නිරපේක්ෂ THI අගයක් හෝ ධන දෛනික කිරි දෙවීම් ගණනක්, නැතිනම් දෙකම නම් කර දෙන්න. විකල්ප අතර අනුමාන නොකරමි.',
                'முன்மொழியும் மதிப்புகளைத் தெளிவுபடுத்தவும். ஒரு முழுமையான THI மற்றும்/அல்லது ஒரு நேர்மறை தினசரி கறவை எண்ணிக்கையைப் பெயரிட்டுத் தரவும். மாற்றுகளுக்கு இடையில் ஊகிக்க மாட்டேன்.')
        awaiting=result['context'].get('awaiting')
        if awaiting=='simulation_cow':
            return pick('Which cow should I use for this what-if? Reply with its approved cow reference. I have kept the proposed scenario details; C2 currently estimates one cow at a time.',
                'මෙම විකල්ප තත්ත්වයට කුමන ගවයා භාවිතා කළ යුතුද? අනුමත ගව හැඳුනුම දෙන්න. යෝජිත තත්ත්ව විස්තර මතකයේ තබා ඇත. C2 දැනට එක් ගවයෙකු බැගින් ඇස්තමේන්තු කරයි.',
                'இந்த மாற்றுச் சூழலுக்கு எந்தப் பசுவைப் பயன்படுத்த வேண்டும்? அங்கீகரிக்கப்பட்ட பசுக் குறிப்பைத் தரவும். முன்மொழிந்த விவரங்களை வைத்துள்ளேன். C2 தற்போது ஒரு பசுவை மட்டும் மதிப்பிடுகிறது.')
        if awaiting=='simulation_thi':
            return pick('What absolute THI value should I test for that cow? Reply with the proposed THI; I will run C2 internally once the required details are complete.',
                'එම ගවයා සඳහා පරීක්ෂා කළ යුතු නිරපේක්ෂ THI අගය කුමක්ද? යෝජිත THI දෙන්න. අවශ්‍ය විස්තර සම්පූර්ණ වූ විට C2 අභ්‍යන්තරව ක්‍රියාත්මක කරමි.',
                'அந்தப் பசுவிற்கு எந்த முழுமையான THI மதிப்பைச் சோதிக்க வேண்டும்? முன்மொழியும் THI ஐத் தரவும். தேவையான விவரங்கள் முழுமையானதும் C2 ஐ உள்ளே இயக்குவேன்.')
        if awaiting=='simulation_milkings':
            return pick('How many milkings per day should I test for that cow? Supply a positive absolute frequency; I will run C2 internally when the details are complete.',
                'එම ගවයා සඳහා දිනකට කිරි දෙවීම් කීයක් පරීක්ෂා කළ යුතුද? ධන නිරපේක්ෂ වාර ගණනක් දෙන්න. විස්තර සම්පූර්ණ වූ විට C2 අභ්‍යන්තරව ක්‍රියාත්මක කරමි.',
                'அந்தப் பசுவிற்கு தினசரி எத்தனை கறவைகளைச் சோதிக்க வேண்டும்? நேர்மறையான முழுமையான எண்ணிக்கையைத் தரவும். விவரங்கள் முழுமையானதும் C2 ஐ உள்ளே இயக்குவேன்.')
        return pick('Should I change THI, milking frequency, or both—and to what absolute values? C2 supports those one-day, per-cow what-ifs. I will run it internally after the required details are supplied.',
            'THI, කිරි දෙවීම් වාර ගණන හෝ දෙකම වෙනස් කළ යුතුද? නිරපේක්ෂ ඉලක්ක අගයන් කුමක්ද? C2 එක් ගවයෙකු සඳහා එක් දින තත්ත්ව සහාය දක්වයි. විස්තර ලැබුණු පසු අභ්‍යන්තරව ක්‍රියාත්මක කරමි.',
            'THI, கறவை எண்ணிக்கை அல்லது இரண்டையும் மாற்ற வேண்டுமா? எந்த முழுமையான மதிப்புகளுக்கு? C2 ஒரு பசுவிற்கான ஒரு நாள் மாற்றங்களை ஆதரிக்கிறது. விவரங்கள் கிடைத்ததும் உள்ளே இயக்குவேன்.')
    if state=='cancelled':
        return pick('The pending what-if has been cancelled. C2 was not run.','පොරොත්තු අනුකරණය අවලංගු කර ඇත. C2 ක්‍රියාත්මක කර නැත.','நிலுவையிலுள்ள மாற்றுச் சூழல் ரத்து செய்யப்பட்டது. C2 இயக்கப்படவில்லை.')
    if state=='causal':
        return pick('C2 can estimate an observational what-if difference, but cannot establish a cause, diagnosis or verified treatment benefit.',
            'C2 නිරීක්ෂණ දත්ත මත වෙනසක් ඇස්තමේන්තු කරයි. හේතුවක්, රෝග නිර්ණයක් හෝ තහවුරු කළ ප්‍රතිකාර ප්‍රතිලාභයක් සනාථ කළ නොහැක.',
            'C2 கண்காணிப்புத் தரவு சார்ந்த மாற்றை மதிப்பிடும். காரணம், நோயறிதல் அல்லது உறுதிப்படுத்தப்பட்ட சிகிச்சைப் பயனை நிரூபிக்க முடியாது.')
    if state=='cow_scope':
        return pick('A numerical whole-herd effect is not available from the installed simulator. I can review recorded farm milk comparisons or stored forecasts as background. An individual estimate is optional; no animal was selected and no herd prediction was generated.',
            'පවතින අනුකාරකයෙන් මුළු රංචුවට සංඛ්‍යාත්මක බලපෑමක් ලබා ගත නොහැක. පසුබිම ලෙස වාර්තාගත කිරි සංසන්දන හෝ ගබඩා කළ පුරෝකථන සමාලෝචනය කළ හැක. තනි ගව ඇස්තමේන්තුවක් අවශ්‍ය නම් පමණක් ඉල්ලන්න. සතෙකු තෝරා හෝ රංචු පුරෝකථනයක් නිර්මාණය කර නැත.',
            'நிறுவிய உருவகப்படுத்தி முழு மந்தைக்கான எண்ணியல் விளைவை வழங்காது. பின்னணியாக பதிவான பால் ஒப்பீடுகளையோ சேமித்த முன்னறிவிப்புகளையோ மீளாய்வு செய்யலாம். தனிப் பசு மதிப்பீடு விருப்பத் தேர்வு. எந்த விலங்கும் தேர்ந்தெடுக்கப்படவில்லை; மந்தை முன்னறிவிப்பு உருவாக்கப்படவில்லை.')
    if state=='horizon':
        return pick('C2 supports only the next calendar day after its latest usable recorded cow-day. It cannot run a weekly, monthly or multi-day simulation.',
            'C2 අවසන් භාවිත කළ හැකි වාර්තාගත ගව දිනයට පසු දිනය පමණක් සහාය දක්වයි. සතිපතා, මාසික හෝ බහු දින අනුකරණයක් ක්‍රියාත්මක කළ නොහැක.',
            'C2 கடைசிப் பயன்படக்கூடிய பதிவான பசு நாளுக்கு அடுத்த நாளை மட்டுமே ஆதரிக்கிறது. வார, மாத அல்லது பல நாள் உருவகப்படுத்தலை இயக்க முடியாது.')
    if state == 'unsupported':
        return pick('C2 currently supports THI exposure and milking-frequency what-ifs only. Feed and concentrate scenarios are unsupported because their units and intervention meaning are not established. No model was run.',
            'C2 දැනට සහාය දක්වන්නේ THI නිරාවරණය සහ කිරි දෙවීම් වාර ගණන වෙනස් කරන තත්ත්ව සඳහා පමණි. ඒකක සහ මැදිහත්වීමේ අර්ථය තහවුරු නැති නිසා ආහාර තත්ත්ව සහාය නොදක්වයි. ආකෘතිය ක්‍රියාත්මක කර නැත.',
            'C2 தற்போது THI வெளிப்பாடு மற்றும் கறவை எண்ணிக்கை மாற்றங்களை மட்டுமே ஆதரிக்கிறது. அலகுகளும் தலையீட்டின் பொருளும் உறுதிப்படுத்தப்படாததால் தீவன மாற்றங்கள் ஆதரிக்கப்படவில்லை. மாதிரி இயக்கப்படவில்லை.')
    if state == 'invalid_dates':
        return pick('C2 uses its latest usable recorded cow-day and a one-day horizon. It does not accept historical reference dates or a custom forecast target. Clear the date controls before running this what-if.',
            'C2 අවසන් භාවිත කළ හැකි වාර්තාගත ගව දිනය සහ එක් දින කාල පරාසයක් භාවිතා කරයි. වෙනත් යොමු හෝ ඉලක්ක දිනයන් සහාය නොදක්වයි. අනුකරණයට පෙර දින පාලක හිස් කරන්න.',
            'C2 கடைசிப் பயன்படக்கூடிய பதிவான பசு நாளையும் ஒரு நாள் காலத்தையும் பயன்படுத்துகிறது. கடந்தகாலக் குறிப்புத் தேதிகளையோ தனிப்பட்ட இலக்குத் தேதிகளையோ ஏற்காது. இயக்குவதற்கு முன் தேதி கட்டுப்பாடுகளை அழிக்கவும்.')
    if state in ('api_unavailable', 'invalid_evidence'):
        return pick('The local C2 API did not return usable, matching simulation evidence. Check the backend, model installation/version and local data permissions. No demo result, alternative cow or invented estimate was used.',
            'දේශීය C2 සේවාව ගැළපෙන භාවිතයට සුදුසු අනුකරණ සාක්ෂි ලබා දුන්නේ නැත. පසුපස සේවාව, ආකෘතියේ ස්ථාපනය සහ අනුවාදය, දත්ත අවසර පරීක්ෂා කරන්න. ආදේශක ගවයෙකු හෝ නිර්මාණය කළ අගයක් භාවිතා කර නැත.',
            'உள்ளூர் C2 சேவை பொருந்தும் பயன்படுத்தக்கூடிய உருவகப்படுத்தல் சான்றை வழங்கவில்லை. பின்தளம், மாதிரி நிறுவல்/பதிப்பு மற்றும் உள்ளூர் தரவு அனுமதிகளைச் சரிபார்க்கவும். மாற்றுப் பசுவோ கற்பனை மதிப்போ பயன்படுத்தப்படவில்லை.')
    evidence = result['evidence']
    if state == 'not_ready':
        if evidence['model_support_status']=='OUTSIDE_TRAINING_SUPPORT':
            return pick('C2 withheld this estimate because your proposed inputs are outside the observed training range. No predicted benefit is shown. Review the supplied limits below.',
                'ඔබේ යෝජිත ආදාන නිරීක්ෂිත පුහුණු පරාසයෙන් පිටත නිසා C2 ඇස්තමේන්තුව ලබා දී නැත. පුරෝකථන ප්‍රතිලාභයක් පෙන්වා නැත. පහත සීමා බලන්න.',
                'நீங்கள் முன்மொழிந்த உள்ளீடுகள் பதிவான பயிற்சி வரம்பிற்கு வெளியே இருப்பதால் C2 மதிப்பீடு வழங்கவில்லை. முன்னறிவிக்கப்பட்ட பயன் காட்டப்படவில்லை. கீழுள்ள வரம்புகளைப் பார்க்கவும்.')
        return pick('C2 withheld a usable what-if estimate. The model, baseline feature or checked training support is unavailable. Review the returned status and limitations below; missing predictions have not been filled in.',
            'C2 වෙතින් භාවිතයට සුදුසු අනුකරණ ඇස්තමේන්තුවක් නොලැබුණි. ආකෘතිය, මූලික ආදානය හෝ තහවුරු කළ පුහුණු පරාසය නොමැත. පහත තත්ත්වය සහ සීමා බලන්න. නැති පුරෝකථන පුරවා නැත.',
            'C2 இலிருந்து பயன்படுத்தக்கூடிய மாற்று மதிப்பீடு கிடைக்கவில்லை. மாதிரி, அடிப்படை உள்ளீடு அல்லது சரிபார்த்த பயிற்சி வரம்பு கிடைக்கவில்லை. கீழுள்ள நிலை மற்றும் வரம்புகளைப் பார்க்கவும். விடுபட்ட முன்னறிவிப்புகள் நிரப்பப்படவில்லை.')
    baseline = f"{evidence['baseline_predicted_milk_yield_l_day']:,.2f}"
    predicted = f"{evidence['counterfactual_predicted_milk_yield_l_day']:,.2f}"
    change = f"{evidence['absolute_yield_change_l_day']:+,.2f}"
    percentage = evidence['percentage_yield_change']
    summary = pick(
        f"Using the recorded cow-day {evidence['observed_date']}, model {evidence['model_version']} predicts {baseline} litres/cow/day for {evidence['target_period']} at baseline and {predicted} with your selected inputs. The model difference is {change} litres/cow/day.",
        f"{evidence['observed_date']} වාර්තාගත දිනය භාවිතයෙන් {evidence['model_version']} ආකෘතිය {evidence['target_period']} දිනයට මූලික තත්ත්වයේ ගවයෙකුට දිනකට ලීටර් {baseline} ක් සහ ඔබේ ආදාන සමඟ {predicted} ක් පුරෝකථනය කරයි. ආකෘති වෙනස ගවයෙකුට දිනකට ලීටර් {change} කි.",
        f"{evidence['observed_date']} பதிவான நாளைப் பயன்படுத்தி {evidence['model_version']} மாதிரி {evidence['target_period']} அன்று அடிப்படையில் பசுவுக்கு நாளொன்றுக்கு {baseline} லிட்டரையும் உங்கள் உள்ளீடுகளுடன் {predicted} லிட்டரையும் முன்னறிவிக்கிறது. மாதிரி வேறுபாடு பசுவுக்கு நாளொன்றுக்கு {change} லிட்டர்.")
    if percentage is not None:
        summary += pick(f' The predicted change is {percentage:+.2f}%.', f' පුරෝකථන වෙනස {percentage:+.2f}% කි.', f' முன்னறிவிப்பு மாற்றம் {percentage:+.2f}%.')
    else:
        summary += pick(' Percentage change is unavailable because the predicted baseline is zero.',
            ' පුරෝකථන මූලික අගය බින්දුව නිසා ප්‍රතිශත වෙනස නොමැත.', ' முன்னறிவிப்பு அடிப்படை பூஜ்யமாக இருப்பதால் சதவீத மாற்றம் கிடைக்கவில்லை.')
    return summary + pick(' These are observational model predictions, not measured outcomes, a verified causal benefit or a management recommendation. THI changes do not represent a specified cooling action; operational feasibility is unverified.',
        ' මේවා නිරීක්ෂණ දත්ත මත ආකෘති පුරෝකථන පමණි. මිනුම්, තහවුරු කළ හේතුමය ප්‍රතිලාභ හෝ කළමනාකරණ නිර්දේශ නොවේ. THI වෙනස විශේෂ සිසිලන ක්‍රියාවක් නියෝජනය නොකරයි. මෙහෙයුම් හැකියාව තහවුරු නැත.',
        ' இவை கண்காணிப்புத் தரவு சார்ந்த மாதிரி முன்னறிவிப்புகள் மட்டுமே; அளவீடுகளோ சரிபார்த்த காரணப் பயனோ மேலாண்மைப் பரிந்துரையோ அல்ல. THI மாற்றம் குறிப்பிட்ட குளிர்விப்பு நடவடிக்கையைக் குறிக்காது. செயல்படுத்தும் சாத்தியம் சரிபார்க்கப்படவில்லை.')
