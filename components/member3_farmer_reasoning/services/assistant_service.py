"""Grounded Member 3 response builder over approved FarmDataService operations."""
from __future__ import annotations

import re
from uuid import uuid4

from shared.schemas.user import UserRole
from components.member3_farmer_reasoning.services.farm_data_service import FarmDataService
from components.member3_farmer_reasoning.integrations.member2_behavior_adapter import Member2BehaviorAdapter


class AssistantService:
    def __init__(self, data: FarmDataService | None = None, member2: Member2BehaviorAdapter | None = None):
        self.data = data or FarmDataService()
        self.member2 = member2 or Member2BehaviorAdapter()
        self.memory: dict[str, dict] = {}

    def answer(self, query: str, farm_id: str, role: UserRole, language: str, conversation_id: str | None = None) -> dict:
        conversation_id = conversation_id or str(uuid4())
        language = self._detect_language(query, language)
        normalized = self._normalize_question(query)
        if not self._is_dairy_question(normalized): return self._response(conversation_id, language, "domain_guard", "I can’t help with that request because I am the dairy-farm assistant. I can help you understand herd health, milk production, breeding, feed, farm costs, and farm records.", [], [], .99, .99)
        intent = self._intent(normalized)
        response = getattr(self, f"_{intent}")(farm_id, normalized, role, conversation_id, language)
        self.memory[conversation_id] = response.get("memory", {})
        response.pop("memory", None)
        return response

    def _intent(self, text: str) -> str:
        if "second cow" in text or "first cow" in text: return "follow_up"
        if any(x in text for x in ("how many", "count", "lactating", "pregnant", "dry cows")): return "herd_count"
        if any(x in text for x in ("expected to calve", "calv", "inseminat")): return "calving"
        if any(x in text for x in ("feed change", "feed change work", "financial effect", "economic impact")): return "feed_change"
        if any(x in text for x in ("profit", "revenue", "income", "margin", "cost of milk", "milk price")): return "profit_overview"
        if any(x in text for x in ("morning briefing", "yesterday briefing", "daily briefing")): return "morning_briefing"
        if any(x in text for x in ("need attention", "high risk", "vet inspect", "health risk", "cows health", "herd health", "animals health")): return "attention"
        if any(x in text for x in ("this week", "last week", "production decrease", "milk production decrease")): return "weekly_production"
        if any(x in text for x in ("cow", "milk production", "last 30 days", "what happened")): return "animal_history"
        if "mastitis" in text: return "mastitis_knowledge"
        return "farm_summary"

    def _herd_count(self, farm_id, text, role, cid, language):
        s = self.data.herd_summary(farm_id)
        if "lactating" in text: answer = f"{s['lactating']} cows are currently lactating out of {s['total']} animals on the farm."
        elif "dry" in text: answer = f"{s['dry']} cows are currently in the dry-cow group."
        elif "pregnant" in text: answer = f"{s['pregnant']} cows are recorded as pregnant."
        else: answer = f"The farm currently has {s['total']} animals: {s['lactating']} lactating, {s['dry']} dry, and {s['pregnant']} pregnant."
        return self._response(cid, language, "herd_count", answer, [{"source":"animals", "label":"Animal records", "recordIds":[], "freshness":"current records"}], [], .95, .92)

    def _behavioral_context(self, farm_id: str) -> tuple[dict, dict]:
        """Format Member 2's output as non-clinical herd-level context."""
        context = self.member2.response_context(farm_id)
        evidence = {
            "source": "member2_behavior",
            "label": "Herd behaviour and welfare signal",
            "recordIds": [],
            "freshness": f"behaviour confidence {context['confidence']:.0%}",
        }
        sentence = (
            f"Herd behaviour is currently {context['routine']} "
            f"({context['confidence']:.0%} confidence), with a welfare score of "
            f"{context['welfare_score']:.0f}/100. This is herd-level context, "
            "not a diagnosis for an individual cow."
        )
        return context, {"sentence": sentence, "evidence": evidence}

    def _attention(self, farm_id, text, role, cid, language):
        items = self.data.attention_animals(farm_id)
        behavior, behavior_output = self._behavioral_context(farm_id)
        detail = "; ".join(f"{x['animal_id']} ({x['reason']}, {x['priority']} priority)" for x in items)
        answer = f"I found {len(items)} cows that need checking today. The first priority is {items[0]['animal_id']} because the record shows {items[0]['reason'].lower()}. The other cows to review are: {detail}. This is a prompt for inspection, not a diagnosis."
        recs = [f"Inspect {x['animal_id']} and review {x['reason'].lower()}." for x in items]
        if language == "si-Latn":
            answer = f"Ada avadhanaya awashya cows {len(items)} denek innawa: {detail}."
            recs = [f"{item['animal_id']} pariksha karala {item['reason'].lower()} review karanna." for item in items]
        elif language == "si":
            answer = f"අද අවධානය අවශ්‍ය ගවයන් {len(items)} දෙනෙක් සිටී: {detail}."
            recs = [f"{item['animal_id']} පරීක්ෂා කර {item['reason']} සමාලෝචනය කරන්න." for item in items]
        elif language == "ta":
            answer = f"இன்று கவனம் தேவைப்படும் பசுக்கள் {len(items)} உள்ளன: {detail}."
            recs = [f"{item['animal_id']} ஐப் பரிசோதித்து {item['reason']} ஐ மதிப்பாய்வு செய்யவும்." for item in items]
        chart_data = [{"animal_id": item["animal_id"], "risk_score": 88 if item["priority"] == "high" else 65} for item in items]
        answer += " " + behavior_output["sentence"]
        evidence = [{"source":"health_events", "label":"Recent health events", "recordIds":[x["record_id"] for x in items], "freshness":"within 30 days"}, behavior_output["evidence"]]
        return self._response(cid, language, "attention_animals", answer, evidence, recs, .86, .86, priority_items=items, visualization={"type":"bar", "title":"Animals needing attention", "data":chart_data}, memory={"ranked_animals": items}, behavioral_context=behavior)

    def _weekly_production(self, farm_id, text, role, cid, language):
        p = self.data.weekly_production(farm_id)
        behavior, behavior_output = self._behavioral_context(farm_id)
        direction = "increased" if p["change_pct"] >= 0 else "decreased"
        answer = f"This week the farm produced {p['current']:.1f} L of milk. Last week it produced {p['previous']:.1f} L. That means production {direction} by {abs(p['change_pct']):.1f}%. {behavior_output['sentence']} Check the cows and routines behind the change before changing feed or treatment plans."
        daily_totals: dict[str, float] = {}
        for record in self.data.repository.milk_records(farm_id, days=14):
            day = record["date"].isoformat()
            daily_totals[day] = daily_totals.get(day, 0) + record["milk_litres"]
        chart_data = [{"date": day, "milk_litres": round(total, 1)} for day, total in sorted(daily_totals.items())]
        return self._response(cid, language, "weekly_production_comparison", answer, [{"source":"milk_production", "label":"14-day milk records", "recordIds":[], "freshness":"today"}, behavior_output["evidence"]], ["Review Shed 2 feeding and cooling checks.", "Inspect LK-2121 and LK-2193 before changing the ration."], .89, .9, visualization={"type":"line", "title":"Farm milk production – 14 days", "data":chart_data}, behavioral_context=behavior)

    def _animal_history(self, farm_id, text, role, cid, language):
        match = re.search(r"(?:cow\s*#?|cow[_ -]?|lk[- ]?)(\d+)", text, re.I)
        token = (f"LK-{match.group(1)}" if match and re.search(r"\blk[- ]?\d+", text, re.I) else match.group(1) if match else "LK-2121")
        history = self.data.animal_history(farm_id, token)
        if not history:
            missing = f"වත්මන් ගොවිපළ වාර්තා තුළ {token} සතා සොයාගත නොහැකි විය." if language == "si" else f"தற்போதைய பண்ணை பதிவுகளில் {token} விலங்கைக் கண்டுபிடிக்க முடியவில்லை." if language == "ta" else f"I could not find animal {token} in the current farm records."
            return self._response(cid, language, "animal_history", missing, [], [], .98, .98)
        animal = history["animal"]
        change = history["latest"] - history["first"]
        health = history["health"]
        if language == "si":
            answer = f"{animal.animal_id} යනු {animal.group} කාණ්ඩයේ කිරි දෙන {animal.breed} සතෙකි. පසුගිය දින 30 තුළ කිරි ප්‍රමාණය ලීටර් {history['first']:.1f} සිට ලීටර් {history['latest']:.1f} දක්වා ({change:+.1f} L) වෙනස් වී ඇත."
            if health: answer += " මෑත වාර්තාව: " + "; ".join(event["event"] for event in health) + ". මෙය පරීක්ෂා කිරීමට ඇති සලකුණක් පමණි; රෝග නිර්ණයක් නොවේ."
            evidence = [{"source":"milk_production", "label":"දින 30 කිරි වාර්තා", "recordIds":[r["record_id"] for r in history["milk"][-3:]], "freshness":"අද"}, {"source":"health_events", "label":"සෞඛ්‍ය ඉතිහාසය", "recordIds":[e["record_id"] for e in health], "freshness":"පසුගිය දින 30"}]
            recommendations = [f"{animal.animal_id} සතා පරීක්ෂා කර ආහාර සහ ජල ප්‍රවේශය තහවුරු කරන්න.", "ප්‍රතිකාර හෝ ආහාර වෙනස් කිරීමට පෙර කිරි ප්‍රවණතාව සමාලෝචනය කරන්න."]
            chart_title = f"{animal.animal_id} කිරි නිෂ්පාදනය – පසුගිය දින 30"
        elif language == "ta":
            answer = f"{animal.animal_id} என்பது {animal.group} குழுவில் உள்ள பால் தரும் {animal.breed} விலங்கு. கடந்த 30 நாட்களில் பால் அளவு {history['first']:.1f} L இலிருந்து {history['latest']:.1f} L ஆக ({change:+.1f} L) மாறியுள்ளது."
            if health: answer += " சமீபத்திய பதிவு: " + "; ".join(event["event"] for event in health) + ". இது ஆய்வுக்கான அறிகுறி மட்டுமே; நோய் உறுதிப்படுத்தல் அல்ல."
            evidence = [{"source":"milk_production", "label":"30 நாள் பால் பதிவுகள்", "recordIds":[r["record_id"] for r in history["milk"][-3:]], "freshness":"இன்று"}, {"source":"health_events", "label":"சுகாதார வரலாறு", "recordIds":[e["record_id"] for e in health], "freshness":"கடந்த 30 நாட்கள்"}]
            recommendations = [f"{animal.animal_id} விலங்கைச் சோதித்து தீவனம் மற்றும் நீர் அணுகலை உறுதிப்படுத்தவும்.", "சிகிச்சை அல்லது தீவன மாற்றத்திற்கு முன் பால் போக்கை மதிப்பாய்வு செய்யவும்."]
            chart_title = f"{animal.animal_id} பால் உற்பத்தி – கடந்த 30 நாட்கள்"
        else:
            answer = f"{animal.animal_id} is a {animal.status} {animal.breed} in {animal.group}. Over the last 30 days, milk yield changed from {history['first']:.1f} L to {history['latest']:.1f} L ({change:+.1f} L)."
            if health: answer += " The most relevant recent record is: " + "; ".join(event["event"] for event in health) + ". This pattern needs an on-farm check; it does not confirm a disease by itself."
            evidence = [{"source":"milk_production", "label":"30-day milk records", "recordIds":[r["record_id"] for r in history["milk"][-3:]], "freshness":"today"}, {"source":"health_events", "label":"Health history", "recordIds":[e["record_id"] for e in health], "freshness":"within 30 days"}]
            recommendations = [f"Inspect {animal.animal_id} and confirm feed and water intake.", "Review the milk trend before treatment or ration changes."]
            chart_title = f"{animal.animal_id} milk yield – last 30 days"
        return self._response(cid, language, "animal_history", answer, evidence, recommendations, .88, .87, visualization={"type":"line", "title":chart_title, "data":[{"date":r["date"].isoformat(), "milk_litres":r["milk_litres"]} for r in history["milk"]]}, memory={"selected_animal": animal.animal_id})

    def _calving(self, farm_id, text, role, cid, language):
        cows = self.data.next_month_calvings(farm_id)
        answer = "These cows are expected to calve next month: " + ", ".join(f"{x['animal_id']} ({x['expected_calving']})" for x in cows) + ". Prepare their transition area and confirm pregnancy records before the expected dates."
        return self._response(cid, language, "expected_calvings", answer, [{"source":"reproduction", "label":"Pregnancy and expected-calving records", "recordIds":[], "freshness":"current records"}], ["Confirm pregnancy checks and transition-pen readiness."], .92, .9, priority_items=cows)

    def _feed_change(self, farm_id, text, role, cid, language):
        d = self.data.feed_change_impact(farm_id)
        behavior, behavior_output = self._behavioral_context(farm_id)
        outcome = "covered the added cost" if d['daily_net_lkr'] >= 0 else "did not yet cover the added cost"
        answer = f"After the Group A concentrate change, estimated group output increased by {d['daily_gain_litres']:.1f} L/day. At the current milk price, the estimated daily net effect is LKR {d['daily_net_lkr']:,.0f}. In simple terms, the extra milk {outcome}. {behavior_output['sentence']} Keep monitoring before making the ration change permanent."
        return self._response(cid, language, "feed_change_evaluation", answer, [{"source":"decision_memory", "label":"Group A feed decision", "recordIds":[d["record_id"]], "freshness":"14 days since implementation"}, behavior_output["evidence"]], ["Continue monitoring for another week before a permanent ration decision."], .76, .78, economic={"daily_net_lkr":d["daily_net_lkr"], "basis":"recorded decision comparison"}, behavioral_context=behavior)

    def _profit_overview(self, farm_id, text, role, cid, language):
        production = self.data.weekly_production(farm_id)
        answer = (
            f"I can report milk production, but I cannot calculate the farm’s total profit reliably yet. "
            f"The current records show {production['current']:.1f} L this week, but a full profit calculation also needs "
            f"milk-sale price, feed cost, labour, veterinary cost, energy, and other operating costs. "
            f"The available decision record only supports the Group A feed-change comparison, not total NLDB farm profit."
        )
        return self._response(cid, language, "profit_overview", answer, [{"source":"milk_production", "label":"Weekly milk production records", "recordIds":[], "freshness":"today"}], ["Add milk-sale price and operating-cost records to calculate full farm profit.", "Use the feed-change evaluation for the available cost-and-output comparison."], .62, .58)

    def _morning_briefing(self, farm_id, text, role, cid, language):
        production = self.data.weekly_production(farm_id)
        attention = self.data.attention_animals(farm_id)
        behavior, behavior_output = self._behavioral_context(farm_id)
        direction = "up" if production["change_pct"] >= 0 else "down"
        priority = attention[0]
        answer = (
            f"Morning briefing: yesterday’s farm context shows weekly milk production {direction} "
            f"{abs(production['change_pct']):.1f}% compared with the prior week. "
            f"{len(attention)} animals need follow-up; the first priority is {priority['animal_id']} "
            f"because of {priority['reason'].lower()}. {behavior_output['sentence']}"
        )
        actions = [f"Inspect {priority['animal_id']} first and record findings.", "Confirm water, cooling, and feeding checks before the afternoon peak."]
        return self._response(cid, language, "morning_briefing", answer, [{"source":"farm_summary", "label":"Yesterday’s operational context", "recordIds":[], "freshness":"morning briefing"}, behavior_output["evidence"]], actions, .87, .88, priority_items=attention, visualization={"type":"bar", "title":"Morning attention priorities", "data":[{"animal_id": item["animal_id"], "risk_score": 88 if item["priority"] == "high" else 65} for item in attention]}, behavioral_context=behavior)

    def _follow_up(self, farm_id, text, role, cid, language):
        ranked = self.memory.get(cid, {}).get("ranked_animals", [])
        index = 1 if "second" in text else 0
        if len(ranked) <= index: return self._response(cid, language, "follow_up", "Please ask for the animals needing attention first, then I can explain a ranked animal.", [], [], .9, .9)
        item = ranked[index]
        return self._animal_history(farm_id, f"Cow {item['animal_id'].split('_')[-1]}", role, cid, language)

    def _mastitis_knowledge(self, farm_id, text, role, cid, language):
        behavior, behavior_output = self._behavioral_context(farm_id)
        answer = "Mastitis can be associated with udder infection, milking hygiene, teat condition, environment, and immune stress. " + behavior_output["sentence"]
        return self._response(cid, language, "general_dairy_knowledge", answer, [behavior_output["evidence"]], ["Use farm records and a veterinary assessment for animal-specific decisions."], .8, .7, behavioral_context=behavior)

    def _farm_summary(self, farm_id, text, role, cid, language):
        s = self.data.herd_summary(farm_id); p = self.data.weekly_production(farm_id); attention = self.data.attention_animals(farm_id)
        behavior, behavior_output = self._behavioral_context(farm_id)
        answer = f"Today’s summary: NLDB Ridiyagama Farm has {s['total']} animals. Milk production is {p['change_pct']:+.1f}% compared with last week. {len(attention)} cows have recent health records that need review, so start with {attention[0]['animal_id']} and then confirm water, cooling, and feeding routines. {behavior_output['sentence']}"
        return self._response(cid, language, "farm_summary", answer, [{"source":"farm_summary", "label":"Farm records", "recordIds":[], "freshness":"today"}, behavior_output["evidence"]], ["Review priority health events.", "Confirm cooling, water, and feeding routine."], .86, .86, behavioral_context=behavior)

    @staticmethod
    def _is_dairy_question(text: str) -> bool:
        terms = ("cow", "farm", "milk", "herd", "health", "mastitis", "feed", "calv", "pregnan", "production", "animal", "dairy", "heat", "risk", "lactat", "dry", "briefing")
        return any(term in text for term in terms) or bool(re.search("[අ-෴அ-௺]", text))

    @staticmethod
    def _detect_language(query: str, selected: str) -> str:
        if re.search(r"[අ-෴]", query): return "si"
        if re.search(r"[அ-௺]", query): return "ta"
        if re.search(r"\b(ada|heta|lage|kohomada|eka|balanna|sathun)\b", query, re.I): return "si-Latn"
        return selected

    @staticmethod
    def _normalize_question(query: str) -> str:
        text = query.lower().strip()
        if re.search(r"\b(cows|sathun)\b.*\b(health|roga)\b", text) or "lage health" in text:
            return "cows health need attention"
        return text

    @staticmethod
    def _response(cid, language, intent, answer, evidence, recommendations, confidence, quality, priority_items=None, visualization=None, economic=None, memory=None, behavioral_context=None):
        return {"conversationId":cid, "messageId":str(uuid4()), "language":language, "intent":intent, "answer":answer, "summary":answer, "priorityItems":priority_items or [], "recommendations":[{"action":x,"priority":"high" if i == 0 else "medium"} for i,x in enumerate(recommendations)], "evidence":evidence, "confidence":confidence, "context_quality":quality, "conflicts":[], "economicImpact":economic, "behavioralContext":behavioral_context, "visualization":visualization, "visualizations":[visualization] if visualization else [], "suggestedQuestions":["Which cows need attention today?", "How many cows are pregnant?"], "decisionActions":[], "memory":memory or {}}
