public class Outer
{
    public record SzAddressByParts(String street, String city, String state, String postalCode, String addressType) implements SzAddress
    {
        public String getPluralName()
        {
            return "addresses";
        }
    }
}
