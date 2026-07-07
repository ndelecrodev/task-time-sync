import json

string_json = """{
    "issues": [
        {
            "expand": "renderedFields,names,schema,operations,editmeta,changelog,versionedRepresentations",
            "id": "10072",
            "self": "https://nic17.atlassian.net/rest/api/3/issue/10072",
            "key": "QT-4",
            "fields": {
                "summary": "Teste - tarefa sem responsável e sem prazo",
                "issuetype": {
                    "self": "https://nic17.atlassian.net/rest/api/3/issuetype/10072",
                    "id": "10072",
                    "description": "",
                    "iconUrl": "https://nic17.atlassian.net/rest/api/2/universal_avatar/view/type/issuetype/avatar/10303?size=medium",
                    "name": "Bug",
                    "subtask": false,
                    "avatarId": 10303,
                    "entityId": "a8f359a1-c35f-4a1a-9a13-2b642784acf7",
                    "hierarchyLevel": 0
                },
                "creator": {
                    "self": "https://nic17.atlassian.net/rest/api/3/user?accountId=712020%3Ab09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "accountId": "712020:b09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "emailAddress": "nicolas.20260225@institutojef.org.br",
                    "avatarUrls": {
                        "48x48": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "24x24": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "16x16": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "32x32": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png"
                    },
                    "displayName": "Nicolas Delecrode",
                    "active": true,
                    "timeZone": "America/Sao_Paulo",
                    "accountType": "atlassian"
                },
                "created": "2026-07-06T03:29:08.243-0300",
                "resolutiondate": null,
                "duedate": null,
                "description": null,
                "assignee": null,
                "priority": {
                    "self": "https://nic17.atlassian.net/rest/api/3/priority/4",
                    "iconUrl": "https://nic17.atlassian.net/images/icons/priorities/low_new.svg",
                    "name": "Low",
                    "id": "4"
                },
                "updated": "2026-07-06T03:29:42.650-0300",
                "status": {
                    "self": "https://nic17.atlassian.net/rest/api/3/status/10066",
                    "description": "",
                    "iconUrl": "https://nic17.atlassian.net/images/icons/statuses/generic.png",
                    "name": "A fazer",
                    "id": "10066",
                    "statusCategory": {
                        "self": "https://nic17.atlassian.net/rest/api/3/statuscategory/2",
                        "id": 2,
                        "key": "new",
                        "colorName": "blue-gray",
                        "name": "To Do"
                    }
                },
                "labels": []
            }
        },
        {
            "expand": "renderedFields,names,schema,operations,editmeta,changelog,versionedRepresentations",
            "id": "10070",
            "self": "https://nic17.atlassian.net/rest/api/3/issue/10070",
            "key": "QT-2",
            "fields": {
                "summary": "Teste - tarefa completa com todos os campos",
                "issuetype": {
                    "self": "https://nic17.atlassian.net/rest/api/3/issuetype/10069",
                    "id": "10069",
                    "description": "",
                    "iconUrl": "https://nic17.atlassian.net/rest/api/2/universal_avatar/view/type/issuetype/avatar/10318?size=medium",
                    "name": "Task",
                    "subtask": false,
                    "avatarId": 10318,
                    "entityId": "c519ffb2-21d1-4d40-b603-0ecf8400481e",
                    "hierarchyLevel": 0
                },
                "creator": {
                    "self": "https://nic17.atlassian.net/rest/api/3/user?accountId=712020%3Ab09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "accountId": "712020:b09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "emailAddress": "nicolas.20260225@institutojef.org.br",
                    "avatarUrls": {
                        "48x48": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "24x24": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "16x16": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "32x32": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png"
                    },
                    "displayName": "Nicolas Delecrode",
                    "active": true,
                    "timeZone": "America/Sao_Paulo",
                    "accountType": "atlassian"
                },
                "created": "2026-07-06T03:24:27.236-0300",
                "resolutiondate": null,
                "duedate": "2026-07-08",
                "description": null,
                "assignee": {
                    "self": "https://nic17.atlassian.net/rest/api/3/user?accountId=712020%3Ab09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "accountId": "712020:b09cd64b-55e3-47fe-b3d9-85a6e309f9d9",
                    "emailAddress": "nicolas.20260225@institutojef.org.br",
                    "avatarUrls": {
                        "48x48": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "24x24": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "16x16": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png",
                        "32x32": "https://secure.gravatar.com/avatar/e2fffcf138552d552f8c0e35dd0031c7?d=https%3A%2F%2Favatar-management--avatars.us-west-2.prod.public.atl-paas.net%2Finitials%2FND-6.png"
                    },
                    "displayName": "Nicolas Delecrode",
                    "active": true,
                    "timeZone": "America/Sao_Paulo",
                    "accountType": "atlassian"
                },
                "priority": {
                    "self": "https://nic17.atlassian.net/rest/api/3/priority/2",
                    "iconUrl": "https://nic17.atlassian.net/images/icons/priorities/high_new.svg",
                    "name": "High",
                    "id": "2"
                },
                "updated": "2026-07-06T03:28:06.073-0300",
                "status": {
                    "self": "https://nic17.atlassian.net/rest/api/3/status/10066",
                    "description": "",
                    "iconUrl": "https://nic17.atlassian.net/images/icons/statuses/generic.png",
                    "name": "A fazer",
                    "id": "10066",
                    "statusCategory": {
                        "self": "https://nic17.atlassian.net/rest/api/3/statuscategory/2",
                        "id": 2,
                        "key": "new",
                        "colorName": "blue-gray",
                        "name": "To Do"
                    }
                },
                "labels": [
                    "Front-End"
                ]
            }
        }
    ],
    "isLast": true
}"""

dados = json.loads(string_json)

for issue in dados["issues"]:    
    if issue["fields"].get("assignee") is None:
        print("It's None")
    else:
        print(issue["fields"]["assignee"].get("displayName","Não informado"))