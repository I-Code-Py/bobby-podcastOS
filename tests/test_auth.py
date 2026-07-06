def test_unauthenticated_request_redirects_to_login(client):
    response = client.get("/clippers", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_then_access(client, admin_user, extract_csrf):
    csrf = extract_csrf(client.get("/login").text)
    response = client.post("/login", data={
        "email": "admin@test.fr", "password": "motdepasse-solide",
        "next": "/clippers", "csrf_token": csrf,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/clippers"

    page = client.get("/clippers")
    assert page.status_code == 200
    assert "Clippeurs" in page.text


def test_wrong_password_is_rejected(client, admin_user, extract_csrf):
    csrf = extract_csrf(client.get("/login").text)
    client.post("/login", data={
        "email": "admin@test.fr", "password": "mauvais-mot-de-passe",
        "next": "/", "csrf_token": csrf,
    })
    response = client.get("/clippers", follow_redirects=False)
    assert response.status_code == 303  # toujours pas connecté


def test_post_without_csrf_token_is_rejected(logged_client):
    response = logged_client.post("/clippers", data={"name": "Sans CSRF"},
                                  follow_redirects=False)
    assert response.status_code == 403


def test_create_clipper_via_ui(logged_client, extract_csrf):
    csrf = extract_csrf(logged_client.get("/clippers").text)
    response = logged_client.post("/clippers", data={
        "name": "Clippeur UI",
        "youtube_channel_url": "https://youtube.com/@clippeur",
        "tiktok_profile_url": "", "instagram_profile_url": "", "notes": "",
        "csrf_token": csrf,
    }, follow_redirects=True)
    assert response.status_code == 200
    assert "Clippeur UI" in response.text


def test_viewer_cannot_mutate(client, db, extract_csrf):
    from app.core.auth import service

    service.create_user(db, "viewer@test.fr", "motdepasse-solide", "viewer")
    csrf = extract_csrf(client.get("/login").text)
    client.post("/login", data={
        "email": "viewer@test.fr", "password": "motdepasse-solide",
        "next": "/", "csrf_token": csrf,
    })
    page = client.get("/clippers")
    csrf = extract_csrf(page.text) if 'csrf_token' in page.text else csrf
    response = client.post("/clippers", data={"name": "Interdit", "csrf_token": csrf},
                           follow_redirects=False)
    assert response.status_code == 403
