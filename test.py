from pydantic import BaseModel, computed_field

class Retangulo(BaseModel):
    largura: float
    altura: float

    @computed_field
    @property
    def area(self) -> float:
        return self.largura * self.altura

# Exemplo de uso
d = {
    "largura": 5.0,
    "altura":4.0 
}
forma = Retangulo(**d)

# Acessa como atributo, sem usar parênteses
print(forma.area)  
# Saída: 20.0

# Inclui a propriedade 'area' no dicionário serializado
print(forma.model_dump()) 
# Saída: {'largura': 5.0, 'altura': 4.0, 'area': 20.0}
