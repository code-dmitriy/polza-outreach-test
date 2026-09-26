from src.textnorm import canon, domain_core, match_score, name_tokens, registrable_domain


def test_domain_core_strips_www_and_tld():
    assert domain_core("https://www.mgwmachine.com/about") == "mgwmachine"
    assert domain_core("internor.com.cn") == "internor"
    assert domain_core("jat-carbide.com") == "jatcarbide"


def test_registrable_domain_handles_multilevel_tld():
    assert registrable_domain("mail.internor.com.cn") == "internor.com.cn"
    assert registrable_domain("www.hnc.su") == "hnc.su"


def test_name_tokens_drops_legal_forms_and_industry_noise():
    assert name_tokens("ТД Ункомтех") == ["ункомтех"]
    assert name_tokens("Ezhong Heavy Machinery") == ["ezhong"]
    # Если чистить нечего — не отдаём пустой список
    assert name_tokens("HNC") == ["hnc"]


def test_canon_bridges_translit_and_domain_spelling():
    # Ровно тот случай, ради которого канонизация и написана
    assert canon("unkomteh") == canon("uncomtech")
    assert canon("tehnosfera") == canon("technosphera")


def test_match_score_recognises_own_domain():
    assert match_score("ТД Ункомтех", "uncomtech.ru") == 1.0
    assert match_score("РИЦ Техносфера", "technosphera.ru") == 1.0
    assert match_score("Fengyi Yinhu", "fengyitool.com") >= 0.8
    assert match_score("Howfit Science", "howfit-press.com") >= 0.8


def test_match_score_rejects_foreign_domain():
    assert match_score("Tengzhong Machinery", "uncomtech.ru") < 0.55
    assert match_score("JAT Cemented Carbide", "jillionsupply.com") < 0.55
    assert match_score("Tesid Equipment", "unimach.ru") < 0.55
