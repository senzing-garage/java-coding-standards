public class Demo
{
    String run(Status status)
    {
        String message = switch (status) {
            case OK -> "fine";
            case BAD -> "broken";
            default -> "unknown";
        };
        return message;
    }
}
