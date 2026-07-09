public class Demo
{
    public void assign(java.util.Map<String, Object> result)
    {
        boolean somewhatLongFlagName = false;
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                       "a quite long string literal that the developer placed at a low column"))));
    }
}
