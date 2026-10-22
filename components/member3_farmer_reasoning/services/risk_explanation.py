"""Explain validated historical C4 evidence with clearly separated record-review suggestions."""


def explain_risk(evidence, language='en'):
    """No thresholds, rankings, diagnoses or source-recommended interventions are inferred."""
    if language not in ('en','si','ta'):
        raise ValueError('Unsupported explanation language')
    def words(en,si,ta):return {'en':en,'si':si,'ta':ta}[language]
    def n(value):
        return words('not supplied','ලබා දී නැත','வழங்கப்படவில்லை') if value is None else f'{value:,.2f}'
    day=evidence['assessment_date']
    sections=[]
    sections.append(words('What this tells you:','මෙයින් කියවෙන්නේ කුමක්ද:','இது என்ன சொல்கிறது:')+'\n'+words(
        f'This assessment describes a historical model result for {day}. It can help you decide which records to review, but it does not establish whether the farm needed an intervention or describe conditions today.',
        f'මෙය {day} දිනයට අදාළ අතීත ආකෘති ප්‍රතිඵලයකි. එය පරීක්ෂා කළ යුතු වාර්තා තෝරාගැනීමට උපකාරී වේ. එම දිනයේ කළමනාකරණ වෙනසක් අවශ්‍ය වූවාද යන්න හෝ අද ගොවිපළේ තත්ත්වය මෙයින් තහවුරු නොවේ.',
        f'இது {day} தேதிக்கான கடந்தகால மாதிரி முடிவு. எந்தப் பதிவுகளை மீளாய்வு செய்வது என்பதைத் தீர்மானிக்க இது உதவும். அன்றைய தினம் மேலாண்மை மாற்றம் தேவையா என்பதையோ இன்றைய பண்ணை நிலைமையையோ இது உறுதிப்படுத்தாது.'))

    checks=[]
    if evidence.get('climate_score') is not None:
        checks.append(words('Check the temperature and humidity records for that date.',
            'එම දිනයේ උෂ්ණත්වය සහ ආර්ද්‍රතාව පිළිබඳ වාර්තා පරීක්ෂා කරන්න.',
            'அந்தத் தேதியின் வெப்பநிலை மற்றும் ஈரப்பதப் பதிவுகளைப் பார்க்கவும்.'))
    if evidence.get('operational_score') is not None:
        checks.append(words("Review that day's milking and farm-operation records with the farm manager.",
            'එම දිනයේ කිරි දෙවීම සහ ගොවිපළ වැඩකටයුතු පිළිබඳ වාර්තා කළමනාකරු සමඟ සමාලෝචනය කරන්න.',
            'அன்றைய கறவை மற்றும் பண்ணைச் செயல்பாட்டுப் பதிவுகளை மேலாளருடன் மீளாய்வு செய்யவும்.'))
    if evidence.get('biological_score') is not None:
        checks.append(words('Review recorded herd events and check for missing biological inputs.',
            'රංචුවේ වාර්තාගත සිදුවීම් සහ අසම්පූර්ණ ජීව විද්‍යාත්මක දත්ත තිබේදැයි පරීක්ෂා කරන්න.',
            'பதிவான மந்தை நிகழ்வுகளையும் விடுபட்ட உயிரியல் உள்ளீடுகளையும் சரிபார்க்கவும்.'))
    checks.append(words('Compare recorded milk totals and their completeness for the same period before deciding on a management change.',
        'කළමනාකරණ වෙනසක් තීරණය කිරීමට පෙර එම කාලයේ කිරි එකතුව සහ වාර්තාවල සම්පූර්ණත්වය සසඳා බලන්න.',
        'மேலாண்மை மாற்றத்தைத் தீர்மானிக்கும் முன் அதே காலத்தின் பதிவான பால் மொத்தங்களையும் பதிவுகளின் முழுமையையும் ஒப்பிடவும்.'))
    sections.append(words('Suggested record checks:','ඊළඟට පරීක්ෂා කළ හැකි වාර්තා:','பரிந்துரைக்கப்படும் பதிவுச் சரிபார்ப்புகள்:')+'\n'+
        words('These are general review suggestions, not actions prescribed by the score.',
            'මේවා සාමාන්‍ය වාර්තා පරීක්ෂණ යෝජනාය. ලකුණ මගින් නියම කළ ක්‍රියාමාර්ග නොවේ.',
            'இவை பொதுவான பதிவுச் சரிபார்ப்பு யோசனைகள். மதிப்பெண் பரிந்துரைத்த நடவடிக்கைகள் அல்ல.')+'\n'+
        '\n'.join('• '+item for item in checks))

    combined=evidence.get('combined_score')
    recorded=words('The combined score is unavailable.' if combined is None else f'Recorded combined research score: {n(combined)}.',
        'ඒකාබද්ධ ලකුණ ලබා දී නැත.' if combined is None else f'වාර්තාගත ඒකාබද්ධ පර්යේෂණ ලකුණ: {n(combined)}.',
        'ஒருங்கிணைந்த மதிப்பெண் வழங்கப்படவில்லை.' if combined is None else f'பதிவான ஒருங்கிணைந்த ஆய்வு மதிப்பெண்: {n(combined)}.')
    parts=[recorded]
    for key,label in [('climate_score',words('Climate','දේශගුණය','காலநிலை')),
                      ('biological_score',words('Biological','ජීව විද්‍යාත්මක','உயிரியல்')),
                      ('operational_score',words('Operations','මෙහෙයුම්','செயல்பாடுகள்'))]:
        parts.append(f'{label}: {n(evidence.get(key))}.')
    parts.append(words('The score scale and action thresholds are unconfirmed, so I cannot label this score high or low or rank its components as causes.',
        'ලකුණු පරිමාණය සහ ක්‍රියාමාර්ග සඳහා සීමා තහවුරු කර නැත. එබැවින් අවදානම ඉහළ හෝ පහළ ලෙස හෝ එක් කොටසක් හේතුව ලෙස තීරණය කළ නොහැක.',
        'மதிப்பெண் அளவும் நடவடிக்கைக்கான வரம்புகளும் உறுதிப்படுத்தப்படவில்லை. எனவே அதிக/குறைந்த அபாயம் என வகைப்படுத்தவோ கூறுகளை காரணங்களாக வரிசைப்படுத்தவோ முடியாது.'))
    if any(evidence.get(key)==0 for key in ('combined_score','climate_score','biological_score','operational_score')):
        parts.append(words('A zero score does not confirm that conditions were normal.',
            'ශූන්‍ය ලකුණකින් තත්ත්වය සාමාන්‍ය බව තහවුරු නොවේ.',
            'பூஜ்ஜிய மதிப்பெண் நிலைமைகள் இயல்பாக இருந்ததை உறுதிப்படுத்தாது.'))
    sections.append(words('Reading the scores:','ලකුණු තේරුම් ගැනීම:','மதிப்பெண்களைப் புரிந்துகொள்வது:')+'\n'+' '.join(parts))

    limits=[]
    if evidence['reference_date']!=day:
        reference=evidence['reference_date']
        limits.append(words(f'This is the latest assessment on or before the requested date, {reference}.',
            f'ඉල්ලූ {reference} දිනයේ හෝ ඊට පෙර ඇති අවසන් ඇගයීම මෙයයි.',
            f'கோரிய {reference} தேதியில் அல்லது அதற்கு முன் உள்ள கடைசி மதிப்பீடு இது.'))
    generated=evidence.get('generated_at')
    if generated:
        created=generated[:10]
        limits.append(words(f'Generated on {created}; this does not prove it was available on the assessment date.',
            f'ප්‍රතිඵලය නිර්මාණය කළ දිනය {created} ය. එය ඇගයීම් දිනයේ ලබාගත හැකිව තිබූ බව මෙයින් තහවුරු නොවේ.',
            f'முடிவு உருவாக்கப்பட்ட தேதி {created}. மதிப்பீட்டுத் தேதியில் அது கிடைத்தது என்பதை இது உறுதிப்படுத்தாது.'))
    else:
        limits.append(words('Its generation time is not supplied.','නිර්මාණ වේලාව ලබා දී නැත.','உருவாக்கிய நேரம் வழங்கப்படவில்லை.'))
    limits.append(words('This experimental assessment is for historical research, not a live alert or a validated prediction.',
        'මෙම පර්යේෂණ ඇගයීම අතීතය සමාලෝචනය කිරීමට පමණි. එය සජීවී අනතුරු ඇඟවීමක් හෝ තහවුරු කළ පුරෝකථනයක් නොවේ.',
        'இந்தப் பரிசோதனை மதிப்பீடு கடந்தகால ஆய்வுக்கானது. இது நேரடி எச்சரிக்கையோ சரிபார்க்கப்பட்ட முன்னறிவிப்போ அல்ல.'))
    sections.append(words('Dates and limits:','දින සහ සීමාවන්:','தேதிகளும் வரம்புகளும்:')+'\n'+' '.join(limits))
    return '\n\n'.join(sections)
