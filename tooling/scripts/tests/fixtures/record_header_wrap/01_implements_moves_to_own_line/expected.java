public class Outer
{
    public record SzFullAddress(String fullAddress, String addressType)
        implements SzAddress
    {
        public String getPluralName()
        {
            return "addresses";
        }
    }
}
