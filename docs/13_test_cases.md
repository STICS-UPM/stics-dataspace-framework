# 13. Casos de Prueba y Correlacion PT5

La correlacion PT5 se usa para conectar funcionalidades, casos de prueba,
flujos operativos y automatizaciones reales. El criterio es comun para
componentes como `Ontology Hub`, `AI Model Hub` y futuros componentes.

## Capas de Referencia

| Capa | Ejemplo | Que representa |
| --- | --- | --- |
| Funcionalidad atomica | `OntHub-33`, `MH-04` | Capacidad concreta del componente |
| Caso PT5 normalizado | `PT5-OH-08`, `PT5-MH-04` | Caso de prueba oficial agrupador |
| Caso operativo | caso de una hoja especifica | Flujo detallado observable |
| Automatizacion | `OH-APP-23` | Test ejecutable real |

La lectura correcta es:

```text
funcionalidad atomica
  -> caso PT5 normalizado
    -> caso operativo del componente
      -> automatizacion real
```

## Inventario Minimo por Componente

Cada componente debe documentar:

| Pieza | Proposito |
| --- | --- |
| Funcionalidades atomicas | Cobertura fina |
| Casos PT5 | Normalizacion comparable |
| Casos operativos | Flujo funcional concreto |
| Automatizacion | Evidencia ejecutable |
| Estado de cobertura | `si`, `parcial`, `no` |
| Observaciones | Gaps o diferencias de alcance |

## Uso por Tipo de Suite

La suite funcional se mapea primero contra la hoja especifica del componente,
porque ahi esta el flujo operativo detallado.

La suite de integracion se mapea primero contra los casos PT5 normalizados,
porque ahi esta la referencia estable de evaluacion.

## Ejemplo Aplicado a Ontology Hub

| Referencia | Rango |
| --- | --- |
| Funcionalidades atomicas | `OntHub-1` a `OntHub-56` |
| Casos PT5 | `PT5-OH-01` a `PT5-OH-16` |
| Casos operativos | `27` casos de la hoja `Ontology Hub` |
| Automatizacion funcional | `OH-APP-00`, `OH-APP-01`, `OH-APP-03` a `OH-APP-27` |

## Resultado Practico

Este criterio permite decir con precision si una prueba cubre:

- comportamiento funcional observable;
- integracion tecnica;
- caso PT5 normalizado;
- funcionalidad atomica;
- solo una parte del flujo esperado.

Cuando haya discrepancia entre hojas, la documentacion del componente debe
explicar la lectura aplicada y conservar la matriz de trazabilidad.
