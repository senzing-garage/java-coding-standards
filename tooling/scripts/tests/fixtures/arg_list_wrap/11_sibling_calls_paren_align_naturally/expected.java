import java.util.List;
import javax.json.JsonValue;

public class Demo
{
    public java.util.List<Object> params()
    {
        java.util.List<Object> result = new java.util.ArrayList<>();
        result.add(arguments(123.456F, JsonValue.ValueType.NUMBER));
        result.add(
            arguments(new Object[] { 10L, 5.5, true, "three" },
                      JsonValue.ValueType.ARRAY));
        result.add(
            arguments(List.of(10L, 5.5, true, "three"),
                      JsonValue.ValueType.ARRAY));
        return result;
    }

    private Object arguments(Object... args)
    {
        return null;
    }
}
