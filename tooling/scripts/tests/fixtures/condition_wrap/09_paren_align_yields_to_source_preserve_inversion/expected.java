public class Demo
{
    public void assign(java.util.Map<String, Object> result)
    {
        boolean somewhatLongFlagName = false;
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                            result.get("anotherKey")
                                  .toString()))));
    }
}
