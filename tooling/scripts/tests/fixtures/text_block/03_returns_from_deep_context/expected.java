public class Demo
{
    public String render(int status)
    {
        switch (status)
        {
            case ACTIVE:
                return """
                    Status: active
                    State: nominal
                    """;
        }
        return "unknown";
    }
}
