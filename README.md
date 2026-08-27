# k8s-shortener

URL-shortener om Kubernetes mee te leren. Push naar `main` -> GitHub Actions
bouwt op je eigen VPS -> image naar GHCR -> rollout op k3s.

## Wat draait waar

| Onderdeel | Kind | Waarom |
|---|---|---|
| `api` | Deployment (2 replicas) | stateless, pods zijn inwisselbaar |
| `postgres` | StatefulSet + PVC | heeft een vaste identiteit en eigen schijf |
| `shortener` | Ingress | Traefik stuurt poort 80 naar de api-Service |
| `api` | HPA | schaalt 2 -> 8 pods op cpu-gebruik |

## Eenmalig opzetten

```bash
kubectl apply -f deploy/00-namespace.yaml
kubectl -n shortener create secret generic db-credentials \
  --from-literal=username=shortener \
  --from-literal=password="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
```

Het db-wachtwoord staat bewust **niet** in deze repo.

## Handige commando's

```bash
kubectl -n shortener get pods -w          # live meekijken tijdens een deploy
kubectl -n shortener logs -l app=api -f   # logs van alle api-pods
kubectl -n shortener rollout undo deployment/api    # vorige versie terug
kubectl -n shortener get hpa -w           # autoscaler aan het werk
```

## Bekende eigenaardigheid

`deploy/20-api.yaml` zet `replicas: 2`, maar de HPA bepaalt het aantal ook.
Elke `kubectl apply` zet het even terug op 2, waarna de HPA corrigeert.
In productie haal je `replicas` weg zodra een HPA het overneemt.
