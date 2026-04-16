# WiFi Marketing Platform - Documentation Frontend

**Version:** 2.0  
**Date:** Février 2026  
**Public:** Développeurs Frontend (Dashboard Owner)

---

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Authentification](#authentification)
4. [Endpoints API Dashboard](#endpoints-api-dashboard)
5. [Modèles de données](#modèles-de-données)
6. [Gestion des erreurs](#gestion-des-erreurs)
7. [Exemples de flux](#exemples-de-flux)

---

## Vue d'ensemble

### Contexte
Le dashboard permet aux propriétaires (owners) de :
- Configurer leur formulaire de collecte de leads
- Consulter les analytics en temps réel
- Gérer leurs leads collectés
- Sécuriser leur intégration via rotation de clés

### Base URL
```
Production: https://api.votre-domaine.com
Development: http://localhost:8000
```

### Format des requêtes
- **Content-Type:** `application/json`
- **Authentication:** JWT Bearer Token
- **Encoding:** UTF-8

---

## Architecture

### Stack technique requise
- **HTTP Client:** Axios, Fetch API, ou équivalent
- **State Management:** Redux, Zustand, Context API (recommandé)
- **Forms:** React Hook Form, Formik (validation côté client)
- **Charts:** Recharts, Chart.js (pour analytics)

### Cycle de vie utilisateur
```
1. Login → JWT Access Token + Refresh Token
2. Fetch schema config → Affichage éditeur formulaire
3. Update schema → Nouveau snippet généré
4. Fetch analytics → Graphiques et KPIs
5. Fetch leads → Table paginée
6. Token expiry → Refresh automatique
```

---

## Authentification

### 1. Login
**Endpoint:** `POST /api/auth/login/`

**Request:**
```json
{
  "email": "owner@example.com",
  "password": "securepassword"
}
```

**Response (200):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 42,
    "email": "owner@example.com",
    "first_name": "John",
    "last_name": "Doe"
  }
}
```

**Stockage recommandé:**
```javascript
localStorage.setItem('access_token', response.access);
localStorage.setItem('refresh_token', response.refresh);
```

---

### 2. Token Refresh
**Endpoint:** `POST /api/auth/refresh/`

**Request:**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Implémentation Axios Interceptor:**
```javascript
axios.interceptors.response.use(
  response => response,
  async error => {
    if (error.response?.status === 401) {
      const refreshToken = localStorage.getItem('refresh_token');
      const { data } = await axios.post('/api/auth/refresh/', {
        refresh: refreshToken
      });
      localStorage.setItem('access_token', data.access);
      error.config.headers['Authorization'] = `Bearer ${data.access}`;
      return axios(error.config);
    }
    return Promise.reject(error);
  }
);
```

---

### 3. Headers requis
Toutes les requêtes authentifiées doivent inclure :
```javascript
headers: {
  'Authorization': `Bearer ${accessToken}`,
  'Content-Type': 'application/json'
}
```

---

## Endpoints API Dashboard

### Base: `/api/v1/schema/`

---

### 1. GET `/api/v1/schema/config/`
**Description:** Récupère la configuration actuelle du formulaire

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "id": 1,
  "name": "default",
  "schema": {
    "fields": [
      {
        "name": "nom",
        "label": "Nom complet",
        "type": "text",
        "required": true,
        "placeholder": "Jean Dupont"
      },
      {
        "name": "email",
        "label": "Email",
        "type": "email",
        "required": true,
        "placeholder": "jean@example.com"
      },
      {
        "name": "phone",
        "label": "Téléphone",
        "type": "phone",
        "required": false,
        "placeholder": "+229 XX XX XX XX"
      },
      {
        "name": "source",
        "label": "Comment nous avez-vous connu ?",
        "type": "choice",
        "choices": ["Facebook", "Instagram", "Affiche", "Bouche-à-oreille"],
        "required": false
      }
    ]
  },
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "version": 5,
  "enable": true,
  "double_opt_enable": true,
  "integration_snippet": "<script src=\"https://api.example.com/static/core_data/widget.js\" data-public-key=\"a1b2c3d4-e5f6-7890-abcd-ef1234567890\"></script>",
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-02-05T14:22:00Z"
}
```

**Utilisation Frontend:**
```javascript
const fetchConfig = async () => {
  const { data } = await axios.get('/api/v1/schema/config/', {
    headers: { Authorization: `Bearer ${token}` }
  });
  
  setFormFields(data.schema.fields);
  setPublicKey(data.public_key);
  setSnippet(data.integration_snippet);
};
```

---

### 2. POST `/api/v1/schema/update_schema/`
**Description:** Met à jour le schéma du formulaire

**Headers:**
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "schema": {
    "fields": [
      {
        "name": "nom",
        "label": "Nom complet",
        "type": "text",
        "required": true
      },
      {
        "name": "email",
        "label": "Email professionnel",
        "type": "email",
        "required": true
      }
    ]
  },
  "name": "default",
  "enable": true
}
```

**Contraintes de validation:**
- Maximum 5 champs
- Au moins 1 champ `email` OU `phone` obligatoire
- Types autorisés : `text`, `email`, `phone`, `number`, `choice`, `boolean`
- Champ `email` doit avoir `name="email"`
- Champ `choice` doit avoir un array `choices`

**Response (200):**
```json
{
  "id": 1,
  "schema": { ... },
  "version": 6,
  "integration_snippet": "...",
  "updated_at": "2026-02-09T15:45:00Z"
}
```

**Erreurs possibles (400):**
```json
{
  "error": "Schema must contain at least one field of type 'email' or 'phone'"
}
```

```json
{
  "error": "Maximum number of fields is 5"
}
```

**Implémentation React:**
```javascript
const updateSchema = async (fields) => {
  try {
    const { data } = await axios.post('/api/v1/schema/update_schema/', {
      schema: { fields },
      enable: true
    }, {
      headers: { Authorization: `Bearer ${token}` }
    });
    
    toast.success('Formulaire mis à jour avec succès');
    setVersion(data.version);
    setSnippet(data.integration_snippet);
  } catch (error) {
    toast.error(error.response.data.error);
  }
};
```

---

### 3. POST `/api/v1/schema/rotate_key/`
**Description:** Génère une nouvelle clé publique (sécurité)

**Headers:**
```
Authorization: Bearer <access_token>
```

**Request Body:** Aucun

**Response (200):**
```json
{
  "public_key": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "warning": "Update your portal URL with the new key",
  "integration_snippet": "<script src=\"...\" data-public-key=\"f9e8d7c6-...\"></script>"
}
```

**Usage:**
```javascript
const rotateKey = async () => {
  const confirmed = window.confirm(
    'Attention : cela invalidera votre ancien widget. Continuer ?'
  );
  
  if (!confirmed) return;
  
  const { data } = await axios.post('/api/v1/schema/rotate_key/', {}, {
    headers: { Authorization: `Bearer ${token}` }
  });
  
  setPublicKey(data.public_key);
  setSnippet(data.integration_snippet);
  
  toast.warning('Nouvelle clé générée. Mettez à jour votre routeur !');
};
```

---

### Base: `/api/v1/analytics/`

---

### 4. GET `/api/v1/analytics/summary/`
**Description:** Récupère les KPIs et statistiques

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "total_leads": 1523,
  "leads_this_week": 87,
  "verified_leads": 1205,
  "return_rate": 34.2,
  "top_clients": [
    {
      "id": 42,
      "name": "Jean Dupont",
      "email": "jean@example.com",
      "phone": "+22997123456",
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "recognition_level": 45,
      "loyalty_percentage": 90.0,
      "last_seen": "2026-02-07T14:32:10Z",
      "created_at": "2025-11-15T09:20:00Z",
      "is_verified": true
    }
  ],
  "leads_by_hour": [
    {
      "hour": "2026-02-09T08:00:00Z",
      "count": 12
    },
    {
      "hour": "2026-02-09T09:00:00Z",
      "count": 18
    }
  ]
}
```

**Métriques:**
- `total_leads`: Nombre total de leads collectés
- `leads_this_week`: Leads des 7 derniers jours
- `verified_leads`: Leads ayant validé leur email/phone
- `return_rate`: % de clients revenus 3+ fois (recognition_level > 2)
- `top_clients`: Top 20 clients fidèles (max 20 entrées)
- `leads_by_hour`: Distribution des leads sur 24h glissantes

**Affichage Dashboard:**
```javascript
const Dashboard = () => {
  const [stats, setStats] = useState(null);
  
  useEffect(() => {
    const fetchStats = async () => {
      const { data } = await axios.get('/api/v1/analytics/summary/', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setStats(data);
    };
    fetchStats();
  }, []);
  
  return (
    <>
      <KPICard title="Total Leads" value={stats.total_leads} />
      <KPICard title="Cette semaine" value={stats.leads_this_week} />
      <KPICard title="Taux de retour" value={`${stats.return_rate}%`} />
      
      <LineChart data={stats.leads_by_hour} />
      <TopClientsTable data={stats.top_clients} />
    </>
  );
};
```

---

### 5. GET `/api/v1/analytics/leads/`
**Description:** Liste paginée de tous les leads

**Headers:**
```
Authorization: Bearer <access_token>
```

**Query Parameters:**
- `page` (optionnel): Numéro de page (défaut: 1)
- `page_size` (optionnel): Éléments par page (défaut: 20, max: 100)

**Exemple:** `GET /api/v1/analytics/leads/?page=2&page_size=50`

**Response (200):**
```json
{
  "count": 1523,
  "next": "http://api.example.com/api/v1/analytics/leads/?page=3",
  "previous": "http://api.example.com/api/v1/analytics/leads/?page=1",
  "results": [
    {
      "id": 1,
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "email": "jean@example.com",
      "phone": "+22997123456",
      "payload": {
        "nom": "Jean Dupont",
        "email": "jean@example.com",
        "phone": "+22997123456",
        "source": "Facebook"
      },
      "client_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "is_verified": true,
      "recognition_level": 12,
      "created_at": "2026-01-15T08:30:00Z",
      "last_seen": "2026-02-09T14:25:00Z"
    }
  ]
}
```

**Tri:** Par `last_seen` décroissant (les plus récents en premier)

**Table React:**
```javascript
const LeadsTable = () => {
  const [leads, setLeads] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  
  const fetchLeads = async (pageNum) => {
    const { data } = await axios.get(`/api/v1/analytics/leads/?page=${pageNum}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    
    setLeads(data.results);
    setTotal(data.count);
  };
  
  return (
    <Table>
      <thead>
        <tr>
          <th>Nom</th>
          <th>Email</th>
          <th>Téléphone</th>
          <th>Visites</th>
          <th>Vérifié</th>
          <th>Dernière visite</th>
        </tr>
      </thead>
      <tbody>
        {leads.map(lead => (
          <tr key={lead.id}>
            <td>{lead.payload.nom}</td>
            <td>{lead.email}</td>
            <td>{lead.phone}</td>
            <td>{lead.recognition_level}</td>
            <td>{lead.is_verified ? '✓' : '✗'}</td>
            <td>{formatDate(lead.last_seen)}</td>
          </tr>
        ))}
      </tbody>
      <Pagination 
        current={page} 
        total={total} 
        onChange={setPage}
      />
    </Table>
  );
};
```

---

## Modèles de données

### FormSchema
```typescript
interface FormSchema {
  id: number;
  name: string;
  schema: {
    fields: FormField[];
  };
  public_key: string;
  version: number;
  enable: boolean;
  double_opt_enable: boolean;
  integration_snippet: string;
  created_at: string; // ISO 8601
  updated_at: string;
}
```

### FormField
```typescript
interface FormField {
  name: string;
  label: string;
  type: 'text' | 'email' | 'phone' | 'number' | 'choice' | 'boolean';
  required: boolean;
  placeholder?: string;
  choices?: string[]; // Obligatoire si type='choice'
}
```

### Lead (OwnerClient)
```typescript
interface Lead {
  id: number;
  mac_address: string;
  email: string | null;
  phone: string | null;
  payload: Record<string, any>;
  client_token: string;
  is_verified: boolean;
  recognition_level: number;
  created_at: string;
  last_seen: string;
}
```

### Analytics Summary
```typescript
interface AnalyticsSummary {
  total_leads: number;
  leads_this_week: number;
  verified_leads: number;
  return_rate: number; // Pourcentage
  top_clients: TopClient[];
  leads_by_hour: HourlyData[];
}

interface TopClient {
  id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  mac_address: string;
  recognition_level: number;
  loyalty_percentage: number;
  last_seen: string;
  created_at: string;
  is_verified: boolean;
}

interface HourlyData {
  hour: string; // ISO 8601
  count: number;
}
```

---

## Gestion des erreurs

### Codes HTTP
| Code | Signification | Action Frontend |
|------|---------------|-----------------|
| 200 | Success | Afficher les données |
| 201 | Created | Confirmation + rafraîchir |
| 400 | Bad Request | Afficher `error` dans un toast |
| 401 | Unauthorized | Refresh token ou redirect login |
| 403 | Forbidden | Afficher "Accès refusé" |
| 404 | Not Found | Afficher "Ressource introuvable" |
| 500 | Server Error | "Erreur serveur, réessayez" |

### Format d'erreur standard
```json
{
  "error": "Schema must contain at least one field of type 'email' or 'phone'"
}
```

Ou pour les erreurs de validation :
```json
{
  "detail": "Le champ 'email' est obligatoire."
}
```

### Handling React
```javascript
const handleError = (error) => {
  if (error.response) {
    const message = error.response.data.error || 
                    error.response.data.detail || 
                    'Une erreur est survenue';
    toast.error(message);
    
    if (error.response.status === 401) {
      // Token expiré
      refreshToken();
    }
  } else {
    toast.error('Erreur réseau. Vérifiez votre connexion.');
  }
};
```

---

## Exemples de flux

### Flux 1: Édition du formulaire
```
1. User clique "Modifier le formulaire"
2. Frontend: GET /api/v1/schema/config/
3. Afficher éditeur avec `schema.fields`
4. User ajoute/modifie des champs
5. Frontend valide côté client (max 5 champs, email OU phone)
6. Frontend: POST /api/v1/schema/update_schema/
7. Backend retourne nouveau snippet
8. Afficher toast success + copier snippet
```

### Flux 2: Dashboard analytics
```
1. Page load
2. Frontend: GET /api/v1/analytics/summary/
3. Afficher 4 KPI cards
4. Render graphique hourly (Recharts LineChart)
5. Render table top clients (triée par loyalty_percentage)
6. Auto-refresh toutes les 60 secondes
```

### Flux 3: Export leads
```
1. User clique "Exporter CSV"
2. Frontend: GET /api/v1/analytics/leads/?page_size=10000
3. Convertir JSON → CSV côté client
4. Trigger download avec Blob API
```

**Code export CSV:**
```javascript
const exportCSV = async () => {
  const { data } = await axios.get('/api/v1/analytics/leads/?page_size=10000', {
    headers: { Authorization: `Bearer ${token}` }
  });
  
  const csv = [
    ['Nom', 'Email', 'Téléphone', 'Visites', 'Vérifié', 'Créé le'].join(','),
    ...data.results.map(lead => [
      lead.payload.nom || '',
      lead.email || '',
      lead.phone || '',
      lead.recognition_level,
      lead.is_verified ? 'Oui' : 'Non',
      new Date(lead.created_at).toLocaleDateString()
    ].join(','))
  ].join('\n');
  
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `leads_${Date.now()}.csv`;
  a.click();
};
```

---

## Notes techniques

### CORS
Le backend autorise les requêtes depuis :
- `http://localhost:3000` (dev)
- `https://dashboard.votre-domaine.com` (prod)

### Rate Limiting
Aucun rate limiting sur les endpoints dashboard (authentifiés).

### Pagination
- Défaut : 20 éléments par page
- Maximum : 100 éléments par page
- Format standard Django REST Framework

### Dates
Toutes les dates sont en **ISO 8601 UTC**.  
Convertir en local timezone côté frontend :
```javascript
const localDate = new Date(lead.created_at).toLocaleString('fr-FR');
```

### Websockets
Non implémenté. Utiliser polling (refresh toutes les 60s) pour le dashboard.

---

## Support

**API Base URL:** Configurée dans `.env`  
**Documentation interactive:** `/api/docs/` (Swagger)  
**Postman Collection:** Disponible sur demande

---

**Dernière mise à jour:** 09 Février 2026  
**Version API:** v1
